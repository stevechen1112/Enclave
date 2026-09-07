"""Reliable, tenant-scoped transport for every file-based knowledge input."""
from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Any, BinaryIO
from uuid import UUID, uuid4

import aiofiles
import anyio
from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.datastructures import Headers

from app.api import deps
from app.api.deps_permissions import check_document_permission
from app.config import settings
from app.models.upload import UploadPart, UploadSession
from app.models.user import User
from app.platform.intake.capabilities import (
    ALL_FORMAT_SPECS,
    build_input_capability_contract,
)
from app.schemas.upload import (
    UploadCommitRequest,
    UploadSessionCreate,
    UploadSessionResponse,
)
from app.services.intake_context import IntakeContextError, parse_intake_context
from app.services.resumable_upload import cleanup_staging
from app.services.storage import build_storage_key, get_storage_backend

router = APIRouter(prefix="/knowledge/upload-sessions", tags=["upload-sessions"])
_CLASSIFICATIONS = {"public", "internal", "confidential", "restricted"}
_HEX = set("0123456789abcdef")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash_file(path: str) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _open_binary(path: str) -> BinaryIO:
    return open(path, "rb")


def _parts(db: Session, session: UploadSession) -> list[UploadPart]:
    return (
        db.query(UploadPart)
        .filter(UploadPart.tenant_id == session.tenant_id, UploadPart.session_id == session.id)
        .order_by(UploadPart.part_number)
        .all()
    )


def _response(db: Session, session: UploadSession) -> UploadSessionResponse:
    parts = _parts(db, session)
    return UploadSessionResponse(
        id=session.id,
        status=session.status,
        filename=session.filename,
        media_type=session.media_type,
        byte_size=session.byte_size,
        part_size=session.part_size,
        total_parts=session.total_parts,
        received_bytes=session.received_bytes,
        received_parts=session.received_parts,
        acknowledged_parts=[
            {"part_number": part.part_number, "byte_size": part.byte_size, "sha256": part.sha256}
            for part in parts
        ],
        expires_at=session.expires_at,
        asset_id=session.asset_id,
        content_sha256=session.content_sha256,
    )


def _owned(db: Session, user: User, session_id: UUID, *, lock: bool = False) -> UploadSession:
    query = db.query(UploadSession).filter(
        UploadSession.tenant_id == user.tenant_id,
        UploadSession.owner_id == user.id,
        UploadSession.id == session_id,
    )
    if lock:
        query = query.with_for_update()
    session = query.first()
    if session is None:
        # Deliberately indistinguishable across tenant and owner boundaries.
        raise HTTPException(status_code=404, detail="upload session not found")
    if session.status not in {"committed", "aborted", "expired"} and session.expires_at <= _now():
        session.status = "expired"
        db.commit()
        cleanup_staging(session)
    return session


def _assert_mutable(session: UploadSession) -> None:
    if session.status == "expired":
        raise HTTPException(status_code=410, detail="upload session expired")
    if session.status == "aborted":
        raise HTTPException(status_code=409, detail="upload session was aborted")
    if session.status == "committed":
        raise HTTPException(status_code=409, detail="upload session is already committed")
    if session.status == "committing":
        raise HTTPException(status_code=409, detail="upload session commit is in progress")


@router.post("", response_model=UploadSessionResponse, status_code=status.HTTP_201_CREATED)
def create_upload_session(
    payload: UploadSessionCreate,
    db: Annotated[Session, Depends(deps.get_db)],
    current_user: Annotated[User, Depends(deps.get_current_active_user)],
) -> UploadSessionResponse:
    acknowledgement_started = time.perf_counter()
    check_document_permission(current_user, "create")
    clean_name = os.path.basename(payload.filename.strip())
    if not clean_name or clean_name != payload.filename.strip():
        raise HTTPException(status_code=400, detail="filename must not contain a path")
    extension = Path(clean_name).suffix.lower()
    spec = next((item for item in ALL_FORMAT_SPECS if item.extension == extension), None)
    if spec is None:
        raise HTTPException(status_code=415, detail="unsupported file extension")
    contract = build_input_capability_contract(tenant_id=str(current_user.tenant_id))
    capability = next(item for item in contract["formats"] if item["extension"] == extension)
    if capability["processing_status"] == "disabled":
        raise HTTPException(status_code=409, detail=capability["degradation_reasons"] or "format disabled")
    if payload.byte_size > int(capability["max_bytes"]):
        raise HTTPException(status_code=413, detail="file exceeds configured size limit")
    if payload.data_classification not in _CLASSIFICATIONS:
        raise HTTPException(status_code=400, detail="unsupported data classification")
    try:
        context = parse_intake_context(
            json.dumps(payload.context_metadata, ensure_ascii=False)
            if payload.context_metadata
            else None
        )
    except IntakeContextError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    from app.api.v1.endpoints.knowledge_assets import _validated_department
    from app.crud import crud_tenant

    department_id = _validated_department(
        db, tenant_id=current_user.tenant_id, department_id=payload.department_id
    )
    quota = crud_tenant.check_storage_quota(db, current_user.tenant_id, payload.byte_size)
    if not quota.get("allowed", True):
        raise HTTPException(status_code=429, detail={"error": "quota_exceeded", "axis": "storage", **quota})

    requested_part_size = payload.part_size or settings.UPLOAD_SESSION_PART_SIZE
    part_size = max(settings.UPLOAD_SESSION_MIN_PART_SIZE, min(requested_part_size, settings.UPLOAD_SESSION_MAX_PART_SIZE))
    total_parts = math.ceil(payload.byte_size / part_size)
    if total_parts > settings.UPLOAD_SESSION_MAX_PARTS:
        raise HTTPException(status_code=413, detail="file requires too many upload parts")

    existing = (
        db.query(UploadSession)
        .filter(
            UploadSession.tenant_id == current_user.tenant_id,
            UploadSession.idempotency_key == payload.idempotency_key,
        )
        .first()
    )
    if existing is not None:
        identity = (existing.filename, existing.byte_size, existing.media_type)
        requested = (clean_name, payload.byte_size, spec.media_type)
        if identity != requested:
            raise HTTPException(status_code=409, detail="idempotency key belongs to another upload")
        return _response(db, existing)

    session_id = uuid4()
    staging_key = build_storage_key(current_user.tenant_id, session_id, extension)
    storage = get_storage_backend()
    provider_upload_id = storage.create_multipart(staging_key)
    session = UploadSession(
        id=session_id,
        tenant_id=current_user.tenant_id,
        owner_id=current_user.id,
        idempotency_key=payload.idempotency_key,
        filename=clean_name,
        media_type=spec.media_type,
        byte_size=payload.byte_size,
        part_size=part_size,
        total_parts=total_parts,
        title=payload.title,
        department_id=department_id,
        data_classification=payload.data_classification,
        context_metadata=context,
        expected_sha256=payload.expected_sha256,
        staging_key=staging_key,
        provider_upload_id=provider_upload_id,
        expires_at=_now() + timedelta(hours=settings.UPLOAD_SESSION_TTL_HOURS),
    )
    try:
        db.add(session)
        db.flush()
        from app.services.input_operations import record_input_metric

        record_input_metric(
            db,
            tenant_id=current_user.tenant_id,
            journey="upload",
            phase="acknowledgement",
            workload_kind=spec.asset_kind,
            outcome="success",
            duration_ms=round((time.perf_counter() - acknowledgement_started) * 1000),
            correlation_id=str(session.id),
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        storage.abort_multipart(staging_key, provider_upload_id)
        winner = (
            db.query(UploadSession)
            .filter(
                UploadSession.tenant_id == current_user.tenant_id,
                UploadSession.idempotency_key == payload.idempotency_key,
            )
            .first()
        )
        if winner is not None and (
            winner.filename,
            winner.byte_size,
            winner.media_type,
        ) == (clean_name, payload.byte_size, spec.media_type):
            return _response(db, winner)
        raise HTTPException(
            status_code=409, detail="idempotency key belongs to another upload"
        ) from exc
    except Exception:
        db.rollback()
        storage.abort_multipart(staging_key, provider_upload_id)
        raise
    db.refresh(session)
    return _response(db, session)


@router.get("/{session_id}", response_model=UploadSessionResponse)
def get_upload_session(
    session_id: UUID,
    db: Annotated[Session, Depends(deps.get_db)],
    current_user: Annotated[User, Depends(deps.get_current_active_user)],
) -> UploadSessionResponse:
    check_document_permission(current_user, "create")
    return _response(db, _owned(db, current_user, session_id))


@router.put("/{session_id}/parts/{part_number}", response_model=UploadSessionResponse)
async def put_upload_part(
    session_id: UUID,
    part_number: int,
    request: Request,
    db: Annotated[Session, Depends(deps.get_db)],
    current_user: Annotated[User, Depends(deps.get_current_active_user)],
    x_part_sha256: Annotated[str, Header(alias="X-Part-SHA256")],
) -> UploadSessionResponse:
    check_document_permission(current_user, "create")
    checksum = x_part_sha256.lower()
    if len(checksum) != 64 or any(char not in _HEX for char in checksum):
        raise HTTPException(status_code=400, detail="invalid X-Part-SHA256")

    # Do not hold the upload-session row lock while awaiting the request body or
    # object storage. Browsers intentionally send several parts concurrently. A
    # row lock across either await lets another coroutine block the synchronous
    # SQLAlchemy session on the same event loop, preventing the lock holder from
    # resuming and eventually exhausting every web worker (including /health and
    # login). Read the immutable transport contract first, then lock only for the
    # short acknowledgement transaction after all external I/O has completed.
    session = _owned(db, current_user, session_id)
    _assert_mutable(session)
    if part_number < 1 or part_number > session.total_parts:
        raise HTTPException(status_code=400, detail="part number outside session range")
    expected_size = session.part_size
    if part_number == session.total_parts:
        expected_size = session.byte_size - session.part_size * (session.total_parts - 1)

    staging_key = session.staging_key
    provider_upload_id = session.provider_upload_id

    existing = (
        db.query(UploadPart)
        .filter(
            UploadPart.tenant_id == session.tenant_id,
            UploadPart.session_id == session.id,
            UploadPart.part_number == part_number,
        )
        .first()
    )
    if existing is not None:
        if existing.sha256 != checksum or existing.byte_size != expected_size:
            raise HTTPException(status_code=409, detail="part already acknowledged with different content")
        return _response(db, session)

    # End the read-only transaction before a potentially long client upload.
    # Primitive contract values above remain valid for the lifetime of a session.
    db.rollback()

    descriptor, temp_path = tempfile.mkstemp(prefix="enclave-part-")
    os.close(descriptor)
    digest = hashlib.sha256()
    received = 0
    try:
        async with aiofiles.open(temp_path, "wb") as stream:
            async for chunk in request.stream():
                if not chunk:
                    continue
                received += len(chunk)
                if received > expected_size:
                    raise HTTPException(status_code=413, detail="part exceeds expected size")
                digest.update(chunk)
                await stream.write(chunk)
        if received != expected_size:
            raise HTTPException(status_code=400, detail="part size does not match session contract")
        if digest.hexdigest() != checksum:
            raise HTTPException(status_code=422, detail="part checksum mismatch")
        storage = get_storage_backend()
        provider_etag = await anyio.to_thread.run_sync(
            storage.upload_part,
            staging_key,
            provider_upload_id,
            part_number,
            temp_path,
        )

        # Serialize only the small database acknowledgement. There is no await
        # between acquiring this lock and commit, so the event loop cannot strand
        # the lock holder behind a competing request from the same worker.
        session = _owned(db, current_user, session_id, lock=True)
        _assert_mutable(session)
        existing = (
            db.query(UploadPart)
            .filter(
                UploadPart.tenant_id == session.tenant_id,
                UploadPart.session_id == session.id,
                UploadPart.part_number == part_number,
            )
            .first()
        )
        if existing is not None:
            if existing.sha256 != checksum or existing.byte_size != received:
                raise HTTPException(
                    status_code=409,
                    detail="part already acknowledged with different content",
                )
            return _response(db, session)
        db.add(
            UploadPart(
                tenant_id=session.tenant_id,
                session_id=session.id,
                part_number=part_number,
                byte_size=received,
                sha256=checksum,
                provider_etag=provider_etag,
            )
        )
        session.received_parts += 1
        session.received_bytes += received
        session.status = "uploading"
        db.commit()
        db.refresh(session)
        return _response(db, session)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


@router.post("/{session_id}/commit")
async def commit_upload_session(
    session_id: UUID,
    payload: UploadCommitRequest,
    db: Annotated[Session, Depends(deps.get_db)],
    current_user: Annotated[User, Depends(deps.get_current_active_user)],
) -> dict[str, Any]:
    check_document_permission(current_user, "create")
    session = _owned(db, current_user, session_id, lock=True)
    if session.status == "committed" and session.asset_id:
        from app.api.v1.endpoints.knowledge_assets import _asset_dict
        from app.models.asset import SourceAsset

        asset = db.query(SourceAsset).filter(SourceAsset.tenant_id == session.tenant_id, SourceAsset.id == session.asset_id).one()
        return {**_asset_dict(db, asset), "deduplicated": True, "upload_session_id": str(session.id)}
    _assert_mutable(session)
    parts = _parts(db, session)
    if [part.part_number for part in parts] != list(range(1, session.total_parts + 1)):
        raise HTTPException(status_code=409, detail="upload session has missing parts")
    if sum(part.byte_size for part in parts) != session.byte_size:
        raise HTTPException(status_code=409, detail="acknowledged byte total does not match")
    session.status = "committing"
    db.commit()

    assembled = ""
    raw = None
    try:
        storage = get_storage_backend()
        if not session.staging_completed:
            staging_exists = await anyio.to_thread.run_sync(
                storage.exists, session.staging_key
            )
            if not staging_exists:
                await anyio.to_thread.run_sync(
                    storage.complete_multipart,
                    session.staging_key,
                    session.provider_upload_id,
                    [(part.part_number, part.provider_etag) for part in parts],
                )
            session.staging_completed = 1
            db.commit()
        descriptor, assembled = tempfile.mkstemp(
            prefix="enclave-resume-", suffix=Path(session.filename).suffix.lower()
        )
        os.close(descriptor)
        await anyio.to_thread.run_sync(
            storage.get_to_file, session.staging_key, assembled
        )
        content_sha256, byte_size = await anyio.to_thread.run_sync(
            _hash_file, assembled
        )
        expected = payload.expected_sha256 or session.expected_sha256
        if byte_size != session.byte_size:
            raise HTTPException(status_code=422, detail="materialized size mismatch")
        if expected and expected != content_sha256:
            raise HTTPException(status_code=422, detail="final checksum mismatch")

        from app.api.v1.endpoints.knowledge_assets import create_asset

        raw = await anyio.to_thread.run_sync(_open_binary, assembled)
        upload = UploadFile(
            file=raw,
            size=byte_size,
            filename=session.filename,
            headers=Headers({"content-type": session.media_type}),
        )
        asset = await create_asset(
            db=db,
            current_user=current_user,
            file=upload,
            title=session.title,
            source_url=None,
            source_system=None,
            source_record_id=None,
            capture_manifest=None,
            media_type=None,
            idempotency_key=session.idempotency_key,
            department_id=session.department_id,
            data_classification=session.data_classification,
            context_metadata=(
                json.dumps(session.context_metadata, ensure_ascii=False)
                if session.context_metadata
                else None
            ),
        )
        if not raw.closed:
            raw.close()
        session = _owned(db, current_user, session_id, lock=True)
        session.status = "committed"
        session.asset_id = UUID(asset["id"])
        session.content_sha256 = content_sha256
        session.committed_at = _now()
        session.error_json = {}
        from app.services.input_operations import record_input_metric

        session_created = session.created_at
        if session_created.tzinfo is None:
            session_created = session_created.replace(tzinfo=timezone.utc)
        record_input_metric(
            db,
            tenant_id=session.tenant_id,
            journey="upload",
            phase="transfer",
            workload_kind=(
                next(
                    (
                        item.asset_kind
                        for item in ALL_FORMAT_SPECS
                        if item.extension == Path(session.filename).suffix.lower()
                    ),
                    "document",
                )
            ),
            outcome="success",
            duration_ms=round((session.committed_at - session_created).total_seconds() * 1000),
            correlation_id=str(session.id),
            details={"byte_size": session.byte_size, "parts": session.total_parts},
        )
        db.commit()
        await anyio.to_thread.run_sync(storage.delete, session.staging_key)
        return {**asset, "upload_session_id": str(session.id), "content_sha256": content_sha256}
    except Exception as exc:
        db.rollback()
        failed = _owned(db, current_user, session_id, lock=True)
        failed.status = "failed"
        failed.error_json = {"message": str(getattr(exc, "detail", exc))[:1000]}
        db.commit()
        raise
    finally:
        if raw is not None and not raw.closed:
            raw.close()
        if assembled and os.path.exists(assembled):
            os.remove(assembled)


@router.delete("/{session_id}", response_model=UploadSessionResponse)
def abort_upload_session(
    session_id: UUID,
    db: Annotated[Session, Depends(deps.get_db)],
    current_user: Annotated[User, Depends(deps.get_current_active_user)],
) -> UploadSessionResponse:
    check_document_permission(current_user, "create")
    session = _owned(db, current_user, session_id, lock=True)
    if session.status == "committed":
        raise HTTPException(status_code=409, detail="committed upload cannot be aborted")
    if session.status != "aborted":
        cleanup_staging(session)
        session.status = "aborted"
        session.aborted_at = _now()
        db.commit()
    return _response(db, session)
