"""Unified, media-neutral knowledge intake and Asset Library API."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlparse
from uuid import UUID, uuid4

import aiofiles
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api import deps
from app.api.deps_permissions import check_document_permission
from app.config import settings
from app.core.authorization import AuthorizationContext
from app.ingestion.core_adapters import (
    CoreVideoIngestionAdapter,
    LongInterviewAudioIngestionAdapter,
    document_capabilities,
)
from app.models.asset import ASSET_KINDS, AssetRevision, DerivedArtifact, SourceAsset
from app.models.ingestion import IngestionJob, IngestionJobEvent
from app.models.document import Document
from app.models.permission import Department
from app.models.user import User
from app.platform.assets import AssetAccessPolicy
from app.platform.intake import AUDIO_CAPABILITIES, AUDIO_MEDIA_TYPES, VIDEO_MEDIA_TYPES
from app.services.asset_visibility import asset_access_allows, canonical_asset_acl
from app.services.ingestion_orchestrator import get_ingestion_orchestrator
from app.services.intake_context import (
    IntakeContextError,
    apply_intake_metadata,
    assert_file_replay_matches,
    find_idempotent_asset,
    parse_intake_context,
)

router = APIRouter(prefix="/knowledge/assets", tags=["knowledge-assets"])
logger = logging.getLogger(__name__)

_AUDIO_TYPES = dict(AUDIO_MEDIA_TYPES)
_VIDEO_EXTENSIONS = set(VIDEO_MEDIA_TYPES)
_DATA_CLASSIFICATIONS = {"public", "internal", "confidential", "restricted"}
_UNSET = object()


def _validate_source_url(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
        raise HTTPException(
            status_code=400,
            detail="source_url must be an http(s) URL without credentials",
        )
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise HTTPException(
            status_code=400, detail="source_url cannot target a local address"
        )
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return value.strip()
    if not address.is_global:
        raise HTTPException(
            status_code=400, detail="source_url cannot target a private address"
        )
    return value.strip()


def _validated_department(
    db: Session, *, tenant_id: UUID, department_id: UUID | None
) -> UUID | None:
    if department_id is None:
        return None
    exists = (
        db.query(Department.id)
        .filter(
            Department.tenant_id == tenant_id,
            Department.id == department_id,
            Department.is_active.is_(True),
        )
        .first()
    )
    if exists is None:
        raise HTTPException(
            status_code=400, detail="department is not active in this tenant"
        )
    return department_id


def _job_dict(job: IngestionJob | None) -> dict[str, Any] | None:
    if job is None:
        return None
    return {
        "id": str(job.id),
        "status": job.status,
        "phase": job.phase,
        "quality_state": job.quality_state,
        "adapter_key": job.adapter_key,
        "adapter_version": job.adapter_version,
        "requested_capabilities": list(job.requested_capabilities or []),
        "readiness": dict(job.readiness or {}),
        "error": dict(job.error or {}),
        "attempt": int(job.attempt or 0),
        "created_at": job.created_at,
        "completed_at": job.completed_at,
    }


def _asset_dict(
    db: Session,
    asset: SourceAsset,
    *,
    include_history: bool = False,
    revisions_override: list[AssetRevision] | None = None,
    job_override: IngestionJob | None | object = _UNSET,
    readiness_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    revisions = revisions_override
    if revisions is None:
        revisions = (
            db.query(AssetRevision)
            .filter(
                AssetRevision.tenant_id == asset.tenant_id,
                AssetRevision.asset_id == asset.id,
            )
            .order_by(AssetRevision.revision.desc())
            .all()
        )
    current = next(
        (
            revision
            for revision in revisions
            if revision.revision == asset.current_revision
        ),
        revisions[0] if revisions else None,
    )
    job = job_override
    if job is _UNSET and current is not None:
        job = (
            db.query(IngestionJob)
            .filter(
                IngestionJob.tenant_id == asset.tenant_id,
                IngestionJob.asset_revision_id == current.id,
            )
            .order_by(IngestionJob.created_at.desc())
            .first()
        )
    elif job is _UNSET:
        job = None
    result: dict[str, Any] = {
        "id": str(asset.id),
        "asset_kind": asset.asset_kind,
        "title": asset.title,
        "source_system": asset.source_system,
        "data_classification": asset.data_classification,
        "metadata": dict(asset.metadata_json or {}),
        "status": asset.status,
        "current_revision": asset.current_revision,
        "created_at": asset.created_at,
        "updated_at": asset.updated_at,
        "tombstoned_at": asset.tombstoned_at,
        "revision": (
            {
                "id": str(current.id),
                "revision": current.revision,
                "media_type": current.media_type,
                "content_hash": current.content_hash,
                "byte_size": current.byte_size,
                "duration_ms": current.duration_ms,
                "ingestion_status": current.ingestion_status,
                "created_at": current.created_at,
            }
            if current
            else None
        ),
        "job": _job_dict(job if isinstance(job, IngestionJob) else None),
    }
    if readiness_override is None:
        from app.services.asset_readiness import load_asset_readiness_states

        state = load_asset_readiness_states(
            db,
            tenant_id=asset.tenant_id,
            assets=[asset],
            jobs_by_revision=(
                {current.id: job}
                if current is not None and isinstance(job, IngestionJob)
                else {}
            ),
        )[asset.id]
        readiness_override = state.to_dict()
    result.update(readiness_override)
    if include_history:
        result["revisions"] = [
            {
                "id": str(revision.id),
                "revision": revision.revision,
                "media_type": revision.media_type,
                "content_hash": revision.content_hash,
                "byte_size": revision.byte_size,
                "duration_ms": revision.duration_ms,
                "ingestion_status": revision.ingestion_status,
                "created_at": revision.created_at,
            }
            for revision in revisions
        ]
    return result


def _visible_asset(
    db: Session,
    *,
    asset_id: UUID,
    authz: AuthorizationContext,
    include_tombstoned: bool = False,
) -> SourceAsset:
    asset = (
        db.query(SourceAsset)
        .filter(
            SourceAsset.tenant_id == authz.tenant_id,
            SourceAsset.id == asset_id,
        )
        .first()
    )
    if asset is None or (asset.tombstoned_at is not None and not include_tombstoned):
        raise HTTPException(status_code=404, detail="asset not found")
    if not include_tombstoned and not asset_access_allows(db, asset, authz=authz):
        raise HTTPException(status_code=404, detail="asset not found")
    return asset


@router.get("")
def list_assets(
    db: Annotated[Session, Depends(deps.get_db)],
    current_user: Annotated[User, Depends(deps.get_current_active_user)],
    kind: Annotated[str | None, Query()] = None,
    source_system: Annotated[str | None, Query()] = None,
    processing_status: Annotated[str | None, Query()] = None,
    data_classification: Annotated[str | None, Query()] = None,
    department_id: Annotated[UUID | None, Query()] = None,
    updated_after: Annotated[datetime | None, Query()] = None,
    publication_status: Annotated[
        str | None, Query(pattern="^(published|unpublished)$")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[dict[str, Any]]:
    authz = AuthorizationContext.from_user(current_user)
    query = db.query(SourceAsset).filter(
        SourceAsset.tenant_id == current_user.tenant_id,
        SourceAsset.tombstoned_at.is_(None),
    )
    if kind:
        query = query.filter(SourceAsset.asset_kind == kind)
    if source_system:
        query = query.filter(SourceAsset.source_system == source_system)
    if data_classification:
        query = query.filter(SourceAsset.data_classification == data_classification)
    if updated_after:
        query = query.filter(
            func.coalesce(SourceAsset.updated_at, SourceAsset.created_at)
            >= updated_after
        )
    assets = query.order_by(SourceAsset.created_at.desc()).limit(500).all()
    visible_assets = []
    for asset in assets:
        if not asset_access_allows(db, asset, authz=authz):
            continue
        if department_id is not None:
            policy = AssetAccessPolicy.from_mapping(asset.acl_reference or {})
            if str(department_id) not in policy.allowed_department_ids:
                continue
        visible_assets.append(asset)
    if publication_status:
        from app.models.knowledge_unit import (
            KnowledgeUnitRecord,
            KnowledgeUnitRelease,
            KnowledgeUnitReleaseMembership,
            KnowledgeUnitRevision,
        )

        published_ids = {
            row[0]
            for row in db.query(KnowledgeUnitRecord.source_asset_id)
            .join(
                KnowledgeUnitRevision,
                (KnowledgeUnitRevision.tenant_id == KnowledgeUnitRecord.tenant_id)
                & (KnowledgeUnitRevision.unit_id == KnowledgeUnitRecord.id),
            )
            .join(
                KnowledgeUnitReleaseMembership,
                (
                    KnowledgeUnitReleaseMembership.tenant_id
                    == KnowledgeUnitRevision.tenant_id
                )
                & (
                    KnowledgeUnitReleaseMembership.unit_revision_id
                    == KnowledgeUnitRevision.id
                ),
            )
            .join(
                KnowledgeUnitRelease,
                (
                    KnowledgeUnitRelease.tenant_id
                    == KnowledgeUnitReleaseMembership.tenant_id
                )
                & (
                    KnowledgeUnitRelease.id == KnowledgeUnitReleaseMembership.release_id
                ),
            )
            .filter(
                KnowledgeUnitRecord.tenant_id == current_user.tenant_id,
                KnowledgeUnitRecord.source_asset_id.is_not(None),
                KnowledgeUnitRecord.tombstoned_at.is_(None),
                KnowledgeUnitRelease.status == "active",
            )
            .distinct()
        }
        visible_assets = [
            asset
            for asset in visible_assets
            if (asset.id in published_ids) == (publication_status == "published")
        ]
    asset_ids = [asset.id for asset in visible_assets]
    revisions_by_asset: dict[UUID, list[AssetRevision]] = {
        asset_id: [] for asset_id in asset_ids
    }
    if asset_ids:
        revision_rows = (
            db.query(AssetRevision)
            .filter(
                AssetRevision.tenant_id == current_user.tenant_id,
                AssetRevision.asset_id.in_(asset_ids),
            )
            .order_by(AssetRevision.revision.desc())
            .all()
        )
        for revision in revision_rows:
            revisions_by_asset[revision.asset_id].append(revision)
    current_revisions = {
        revision.id: revision
        for asset in visible_assets
        for revision in revisions_by_asset[asset.id]
        if revision.revision == asset.current_revision
    }
    jobs_by_revision: dict[UUID, IngestionJob] = {}
    if current_revisions:
        job_rows = (
            db.query(IngestionJob)
            .filter(
                IngestionJob.tenant_id == current_user.tenant_id,
                IngestionJob.asset_revision_id.in_(list(current_revisions)),
            )
            .order_by(IngestionJob.created_at.desc())
            .all()
        )
        for job in job_rows:
            jobs_by_revision.setdefault(job.asset_revision_id, job)
    from app.services.asset_readiness import load_asset_readiness_states

    readiness_by_asset = load_asset_readiness_states(
        db,
        tenant_id=current_user.tenant_id,
        assets=visible_assets,
        jobs_by_revision=jobs_by_revision,
    )
    rows = []
    for asset in visible_assets:
        revisions = revisions_by_asset[asset.id]
        current = next(
            (item for item in revisions if item.revision == asset.current_revision),
            None,
        )
        rows.append(
            _asset_dict(
                db,
                asset,
                revisions_override=revisions,
                job_override=jobs_by_revision.get(current.id) if current else None,
                readiness_override=readiness_by_asset[asset.id].to_dict(),
            )
        )
    if processing_status:
        lifecycle_values = {
            "received",
            "processing",
            "awaiting_review",
            "answer_ready",
            "needs_attention",
        }
        rows = [
            row
            for row in rows
            if (
                row.get("lifecycle_status") == processing_status
                if processing_status in lifecycle_values
                else (row.get("job") or {}).get("status") == processing_status
            )
        ]
    return rows[:limit]


@router.get("/{asset_id}")
def get_asset(
    asset_id: UUID,
    db: Annotated[Session, Depends(deps.get_db)],
    current_user: Annotated[User, Depends(deps.get_current_active_user)],
) -> dict[str, Any]:
    asset = _visible_asset(
        db,
        asset_id=asset_id,
        authz=AuthorizationContext.from_user(current_user),
    )
    payload = _asset_dict(db, asset, include_history=True)
    if asset.asset_kind in {"audio", "video"}:
        current = (
            db.query(AssetRevision)
            .filter(
                AssetRevision.tenant_id == current_user.tenant_id,
                AssetRevision.asset_id == asset.id,
                AssetRevision.revision == asset.current_revision,
            )
            .first()
        )
        proxy = (
            db.query(DerivedArtifact)
            .filter(
                DerivedArtifact.tenant_id == current_user.tenant_id,
                DerivedArtifact.asset_revision_id == current.id,
                DerivedArtifact.artifact_kind == "media_proxy",
            )
            .order_by(DerivedArtifact.created_at.desc())
            .first()
            if current is not None
            else None
        )
        if proxy is not None:
            from app.services.media_access import create_media_token

            payload["preview_url"] = (
                f"/api/v1/media/artifacts/{proxy.id}/content?token="
                + create_media_token(
                    tenant_id=current_user.tenant_id,
                    user_id=current_user.id,
                    resource_kind="video_artifact",
                    resource_id=proxy.id,
                )
            )
        else:
            payload["preview_url"] = None
    return payload


@router.get("/{asset_id}/status")
def get_asset_status(
    asset_id: UUID,
    db: Annotated[Session, Depends(deps.get_db)],
    current_user: Annotated[User, Depends(deps.get_current_active_user)],
) -> dict[str, Any]:
    asset = _visible_asset(
        db,
        asset_id=asset_id,
        authz=AuthorizationContext.from_user(current_user),
    )
    data = _asset_dict(db, asset)
    return {
        "asset_id": data["id"],
        "status": data["status"],
        "lifecycle_status": data["lifecycle_status"],
        "answer_ready": data["answer_ready"],
        "pending_review_count": data["pending_review_count"],
        "job": data["job"],
    }


@router.get("/{asset_id}/revisions")
def list_asset_revisions(
    asset_id: UUID,
    db: Annotated[Session, Depends(deps.get_db)],
    current_user: Annotated[User, Depends(deps.get_current_active_user)],
) -> list[dict[str, Any]]:
    asset = _visible_asset(
        db,
        asset_id=asset_id,
        authz=AuthorizationContext.from_user(current_user),
    )
    return list(_asset_dict(db, asset, include_history=True)["revisions"])


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_asset(
    db: Annotated[Session, Depends(deps.get_db)],
    current_user: Annotated[User, Depends(deps.get_current_active_user)],
    file: Annotated[UploadFile | None, File()] = None,
    title: Annotated[str | None, Form()] = None,
    source_url: Annotated[str | None, Form()] = None,
    source_system: Annotated[str | None, Form()] = None,
    source_record_id: Annotated[str | None, Form()] = None,
    capture_manifest: Annotated[str | None, Form()] = None,
    media_type: Annotated[str | None, Form()] = None,
    idempotency_key: Annotated[str | None, Form()] = None,
    department_id: Annotated[UUID | None, Form()] = None,
    data_classification: Annotated[str, Form()] = "internal",
    context_metadata: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    check_document_permission(current_user, "create")
    if idempotency_key and len(idempotency_key) > 500:
        raise HTTPException(status_code=400, detail="idempotency_key is too long")
    if capture_manifest and len(capture_manifest.encode("utf-8")) > 64 * 1024:
        raise HTTPException(
            status_code=413, detail="capture_manifest exceeds size limit"
        )
    if data_classification not in _DATA_CLASSIFICATIONS:
        raise HTTPException(status_code=400, detail="unsupported data classification")
    try:
        intake_context = parse_intake_context(context_metadata)
    except IntakeContextError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    department_id = _validated_department(
        db, tenant_id=current_user.tenant_id, department_id=department_id
    )
    modes = sum(
        bool(value) for value in (file, source_url, source_record_id, capture_manifest)
    )
    if modes != 1:
        raise HTTPException(
            status_code=400,
            detail="provide exactly one of file, source_url, source_record_id, or capture_manifest",
        )
    try:
        existing_asset = find_idempotent_asset(
            db,
            tenant_id=current_user.tenant_id,
            idempotency_key=idempotency_key,
        )
        if existing_asset is not None:
            if file is not None:
                clean_name = os.path.basename(file.filename or "")
                assert_file_replay_matches(
                    db,
                    asset=existing_asset,
                    filename=clean_name,
                    byte_size=getattr(file, "size", None),
                )
                await file.close()
            elif source_url is not None:
                normalized_url = _validate_source_url(source_url)
                if (
                    existing_asset.source_system != "web"
                    or existing_asset.source_record_id != normalized_url
                ):
                    raise IntakeContextError(
                        "idempotency key belongs to another source"
                    )
            elif source_record_id is not None:
                expected_system = f"api:{str(source_system or '').strip()}"
                if (
                    existing_asset.source_system != expected_system
                    or existing_asset.source_record_id != source_record_id.strip()
                ):
                    raise IntakeContextError(
                        "idempotency key belongs to another source"
                    )
            return {**_asset_dict(db, existing_asset), "deduplicated": True}
    except IntakeContextError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    from app.api.ingestion_guard import enforce_ingestion_queue_capacity

    enforce_ingestion_queue_capacity()
    if file is not None:
        extension = Path(os.path.basename(file.filename or "")).suffix.lower()
        if extension in _VIDEO_EXTENSIONS:
            from app.api.v1.endpoints.video_assets import upload_video_asset

            legacy = await upload_video_asset(
                file=file,
                db=db,
                current_user=current_user,
                title=title,
                equipment_ids=None,
                applicable_roles=None,
                idempotency_key=idempotency_key,
                department_id=department_id,
                data_classification=data_classification,
                context_metadata=context_metadata,
            )
            asset = (
                db.query(SourceAsset)
                .filter(
                    SourceAsset.tenant_id == current_user.tenant_id,
                    SourceAsset.id == UUID(legacy["id"]),
                )
                .one()
            )
            return {**_asset_dict(db, asset), "deduplicated": False}
        if extension not in _AUDIO_TYPES:
            from app.api.v1.endpoints.documents import upload_document

            document = await upload_document(
                db=db,
                file=file,
                current_user=current_user,
                idempotency_key=idempotency_key,
                department_id=department_id,
                data_classification=data_classification,
                context_metadata=context_metadata,
            )
            asset_id = getattr(document, "source_asset_id", None)
            if asset_id is None:
                raise HTTPException(
                    status_code=500, detail="asset projection unavailable"
                )
            asset = (
                db.query(SourceAsset)
                .filter(
                    SourceAsset.tenant_id == current_user.tenant_id,
                    SourceAsset.id == asset_id,
                )
                .one()
            )
            asset.title = (title or asset.title)[:500]
            db.commit()
            db.refresh(asset)
            return {**_asset_dict(db, asset), "deduplicated": False}
        return await _create_audio_asset(
            db=db,
            file=file,
            current_user=current_user,
            title=title,
            idempotency_key=idempotency_key,
            department_id=department_id,
            data_classification=data_classification,
            intake_context=intake_context,
        )
    if source_url is not None:
        return _create_url_asset(
            db=db,
            current_user=current_user,
            title=title,
            source_url=source_url,
            department_id=department_id,
            data_classification=data_classification,
            idempotency_key=idempotency_key,
            intake_context=intake_context,
        )
    return _create_reference_asset(
        db=db,
        current_user=current_user,
        title=title,
        source_url=source_url,
        source_system=source_system,
        source_record_id=source_record_id,
        capture_manifest=capture_manifest,
        media_type=media_type,
        idempotency_key=idempotency_key,
        department_id=department_id,
        data_classification=data_classification,
        intake_context=intake_context,
    )


def _create_url_asset(
    *,
    db: Session,
    current_user: User,
    title: str | None,
    source_url: str,
    department_id: UUID | None,
    data_classification: str,
    idempotency_key: str | None,
    intake_context: dict[str, Any],
) -> dict[str, Any]:
    """Bridge URL intake to the proven Document URL worker.

    The canonical asset is created immediately, while its first immutable
    content revision is created only after the worker fetches the source. This
    avoids pretending the URL string itself is the fetched source content.
    """
    source_url = _validate_source_url(source_url)
    if len(source_url) > 500:
        raise HTTPException(status_code=400, detail="source_url is too long")
    existing = (
        db.query(SourceAsset)
        .filter(
            SourceAsset.tenant_id == current_user.tenant_id,
            SourceAsset.source_system == "web",
            SourceAsset.source_record_id == source_url,
            SourceAsset.tombstoned_at.is_(None),
        )
        .first()
    )
    if existing is not None:
        return {**_asset_dict(db, existing), "deduplicated": True}

    document = Document(
        tenant_id=current_user.tenant_id,
        filename=(title or source_url)[:500],
        file_type="html",
        file_path=source_url,
        source_type="web",
        source_system="web",
        source_record_id=source_url,
        version=1,
        status="pending",
        uploaded_by=current_user.id,
        department_id=department_id,
    )
    db.add(document)
    db.flush()
    from app.services.asset_projection import project_document

    projection = project_document(db, document)
    asset = projection.asset
    asset.title = document.filename
    asset.status = "processing"
    asset.data_classification = data_classification
    asset.acl_reference = canonical_asset_acl(
        owner_subject_id=current_user.id,
        visibility="restricted" if department_id else "tenant",
        allowed_department_ids=[department_id] if department_id else [],
    )
    asset.metadata_json = {
        **dict(asset.metadata_json or {}),
        "direct_intake": True,
        "source_url": source_url,
    }
    apply_intake_metadata(
        asset, context=intake_context, idempotency_key=idempotency_key
    )
    db.commit()

    dispatched = True
    try:
        from app.tasks.document_tasks import process_url_task

        process_url_task.delay(
            str(document.id), source_url, str(current_user.tenant_id)
        )
    except Exception:
        dispatched = False
        logger.exception("URL asset persisted but broker dispatch failed: %s", asset.id)
        asset.status = "failed"
        document.status = "failed"
        document.error_message = "background processing could not be dispatched"
        db.commit()
    return {
        **_asset_dict(db, asset),
        "deduplicated": False,
        "dispatched": dispatched,
        "capability_plan": {"requested_capabilities": ["extract_text", "layout"]},
    }


async def _create_audio_asset(
    *,
    db: Session,
    file: UploadFile,
    current_user: User,
    title: str | None,
    idempotency_key: str | None,
    department_id: UUID | None,
    data_classification: str,
    intake_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    clean_name = os.path.basename(file.filename or "")
    extension = Path(clean_name).suffix.lower()
    descriptor, temp_path = tempfile.mkstemp(prefix="enclave-asset-", suffix=extension)
    os.close(descriptor)
    digest = hashlib.sha256()
    size = 0
    try:
        async with aiofiles.open(temp_path, "wb") as stream:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.MAX_FILE_SIZE:
                    raise HTTPException(
                        status_code=413, detail="audio exceeds size limit"
                    )
                digest.update(chunk)
                await stream.write(chunk)
    except Exception:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise
    finally:
        await file.close()
    if size == 0:
        os.remove(temp_path)
        raise HTTPException(status_code=400, detail="audio is empty")
    content_hash = digest.hexdigest()
    duplicate = (
        db.query(AssetRevision)
        .join(
            SourceAsset,
            (SourceAsset.tenant_id == AssetRevision.tenant_id)
            & (SourceAsset.id == AssetRevision.asset_id),
        )
        .filter(
            AssetRevision.tenant_id == current_user.tenant_id,
            AssetRevision.content_hash == content_hash,
            SourceAsset.tombstoned_at.is_(None),
        )
        .first()
    )
    if duplicate is not None:
        os.remove(temp_path)
        asset = db.query(SourceAsset).filter(SourceAsset.id == duplicate.asset_id).one()
        return {**_asset_dict(db, asset), "deduplicated": True}
    from app.services.cost_guardrails import (
        MediaDurationError,
        probe_media_duration_ms,
        reserve_media_cost,
    )

    try:
        duration_ms = probe_media_duration_ms(temp_path)
    except MediaDurationError as exc:
        os.remove(temp_path)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    cost_reservation = reserve_media_cost(
        db,
        tenant_id=current_user.tenant_id,
        media_kind="audio",
        duration_ms=duration_ms,
        task_id=f"upload:{content_hash}",
    )
    if not cost_reservation.get("allowed", False):
        db.rollback()
        os.remove(temp_path)
        raise HTTPException(
            status_code=429,
            detail={
                "error": "quota_exceeded",
                "axis": "cost",
                "message": cost_reservation.get("message"),
                "current": cost_reservation.get("current"),
                "limit": cost_reservation.get("limit"),
            },
        )
    from app.crud import crud_tenant

    storage_quota = crud_tenant.lock_and_check_storage_quota(
        db, current_user.tenant_id, size
    )
    if not storage_quota.get("allowed", True):
        os.remove(temp_path)
        raise HTTPException(
            status_code=429,
            detail={
                "error": "quota_exceeded",
                "axis": "storage",
                "message": storage_quota.get("message", "storage quota exceeded"),
                "current": storage_quota.get("current"),
                "limit": storage_quota.get("limit"),
            },
        )
    asset_id = uuid4()
    from app.services.file_scan import scan_file_path
    from app.services.storage import build_storage_key, get_storage_backend

    storage_key = build_storage_key(current_user.tenant_id, asset_id, extension)
    storage = get_storage_backend()
    try:
        scan_file_path(temp_path, clean_name)
        content_uri = storage.put(storage_key, temp_path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
    try:
        acl = canonical_asset_acl(
            owner_subject_id=current_user.id,
            visibility="restricted" if department_id else "tenant",
            allowed_department_ids=[department_id] if department_id else [],
        )
        asset = SourceAsset(
            id=asset_id,
            tenant_id=current_user.tenant_id,
            asset_kind="audio",
            title=(title or clean_name)[:500],
            source_system="upload",
            data_classification=data_classification,
            acl_reference=acl,
            metadata_json={"filename": clean_name, "storage_key": storage_key},
            current_revision=1,
            status="processing",
            created_by=current_user.id,
        )
        apply_intake_metadata(
            asset, context=intake_context, idempotency_key=idempotency_key
        )
        db.add(asset)
        db.flush()
        revision = AssetRevision(
            tenant_id=current_user.tenant_id,
            asset_id=asset.id,
            revision=1,
            media_type=_AUDIO_TYPES[extension],
            content_uri=content_uri,
            content_hash=content_hash,
            byte_size=size,
            duration_ms=duration_ms,
            ingestion_status="queued",
            created_by=current_user.id,
        )
        db.add(revision)
        db.flush()
        job = get_ingestion_orchestrator().ensure_job(
            db,
            tenant_id=current_user.tenant_id,
            asset_revision_id=revision.id,
            capabilities=AUDIO_CAPABILITIES,
            idempotency_key=idempotency_key,
        )
        db.commit()
    except Exception:
        db.rollback()
        try:
            storage.delete(storage_key)
        except Exception:
            logger.exception(
                "failed to clean audio object after intake error: %s", storage_key
            )
        raise
    db.refresh(asset)
    dispatched = True
    try:
        from app.tasks.audio_tasks import process_audio_asset

        process_audio_asset.delay(
            str(current_user.tenant_id), str(revision.id), str(job.id)
        )
    except Exception as exc:
        dispatched = False
        logger.exception("audio job persisted but broker dispatch failed: %s", job.id)
        job = get_ingestion_orchestrator().transition(
            db, job, to_status="running", phase="dispatching"
        )
        get_ingestion_orchestrator().fail(
            db,
            job,
            code="broker_dispatch_failed",
            message=str(exc),
            phase="dispatching",
        )
        asset.status = "failed"
        revision.ingestion_status = "failed"
        db.commit()
    return {
        **_asset_dict(db, asset),
        "deduplicated": False,
        "dispatched": dispatched,
        "capability_plan": _job_dict(job),
    }


def _create_reference_asset(
    *,
    db: Session,
    current_user: User,
    title: str | None,
    source_url: str | None,
    source_system: str | None,
    source_record_id: str | None,
    capture_manifest: str | None,
    media_type: str | None,
    idempotency_key: str | None,
    department_id: UUID | None,
    data_classification: str,
    intake_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if source_url:
        source_url = _validate_source_url(source_url)
    manifest: dict[str, Any] | None = None
    if capture_manifest:
        try:
            parsed = json.loads(capture_manifest)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=400, detail="capture_manifest must be valid JSON"
            ) from exc
        if not isinstance(parsed, dict):
            raise HTTPException(
                status_code=400, detail="capture_manifest must be a JSON object"
            )
        manifest = parsed
    requested_system = str(source_system or "").strip()
    if len(requested_system) > 90:
        raise HTTPException(status_code=400, detail="source_system is too long")
    system = (
        "capture"
        if manifest
        else (
            "web"
            if source_url
            else f"api:{requested_system}"
            if requested_system
            else ""
        )
    )
    record_id = (
        str(manifest.get("capture_id") or uuid4())
        if manifest
        else (source_url or str(source_record_id or "").strip())
    )
    if not system or not record_id:
        raise HTTPException(
            status_code=400, detail="connector source identity is required"
        )
    if len(record_id) > 500:
        raise HTTPException(status_code=400, detail="source_record_id is too long")
    if idempotency_key:
        existing_job = (
            db.query(IngestionJob)
            .filter(
                IngestionJob.tenant_id == current_user.tenant_id,
                IngestionJob.idempotency_key == idempotency_key,
            )
            .first()
        )
        if existing_job is not None:
            existing_revision = (
                db.query(AssetRevision)
                .filter(
                    AssetRevision.tenant_id == current_user.tenant_id,
                    AssetRevision.id == existing_job.asset_revision_id,
                )
                .one()
            )
            existing_asset = (
                db.query(SourceAsset)
                .filter(
                    SourceAsset.tenant_id == current_user.tenant_id,
                    SourceAsset.id == existing_revision.asset_id,
                    SourceAsset.tombstoned_at.is_(None),
                )
                .first()
            )
            if existing_asset is None:
                raise HTTPException(
                    status_code=409,
                    detail="idempotency key references an unavailable asset",
                )
            if (
                existing_asset.source_system != system
                or existing_asset.source_record_id != record_id
            ):
                raise HTTPException(
                    status_code=409, detail="idempotency key belongs to another source"
                )
            return {**_asset_dict(db, existing_asset), "deduplicated": True}
    asset_kind = "web_page" if source_url else "external_record"
    if manifest:
        requested_kind = str(manifest.get("asset_kind") or "").strip()
        if requested_kind:
            if requested_kind not in ASSET_KINDS:
                raise HTTPException(
                    status_code=400, detail="unsupported capture asset kind"
                )
            asset_kind = requested_kind
        elif (media_type or "").startswith("audio/"):
            asset_kind = "audio"
        elif (media_type or "").startswith("video/"):
            asset_kind = "video"
        elif (media_type or "").startswith("image/"):
            asset_kind = "image"
    content_uri = source_url or (
        f"capture://{record_id}" if manifest else f"external://{system}/{record_id}"
    )
    digest = hashlib.sha256(f"{system}\n{record_id}".encode()).hexdigest()
    existing = (
        db.query(SourceAsset)
        .filter(
            SourceAsset.tenant_id == current_user.tenant_id,
            SourceAsset.source_system == system,
            SourceAsset.source_record_id == record_id,
            SourceAsset.tombstoned_at.is_(None),
        )
        .first()
    )
    if existing is not None:
        return {**_asset_dict(db, existing), "deduplicated": True}
    acl = canonical_asset_acl(
        owner_subject_id=current_user.id,
        visibility="restricted" if department_id else "tenant",
        allowed_department_ids=[department_id] if department_id else [],
    )
    asset = SourceAsset(
        id=uuid4(),
        tenant_id=current_user.tenant_id,
        asset_kind=asset_kind,
        title=(
            title
            or (
                str(manifest.get("title"))
                if manifest and manifest.get("title")
                else record_id
            )
        )[:500],
        source_system=system,
        source_record_id=record_id,
        data_classification=data_classification,
        acl_reference=acl,
        metadata_json={
            "direct_intake": True,
            "source_url": source_url,
            "capture_manifest": manifest,
            "upstream_source_system": requested_system or None,
        },
        current_revision=1,
        status="processing",
        created_by=current_user.id,
    )
    apply_intake_metadata(
        asset, context=intake_context, idempotency_key=idempotency_key
    )
    db.add(asset)
    db.flush()
    revision = AssetRevision(
        tenant_id=current_user.tenant_id,
        asset_id=asset.id,
        revision=1,
        media_type=media_type or ("text/html" if source_url else "application/json"),
        content_uri=content_uri,
        content_hash=digest,
        ingestion_status="queued",
        created_by=current_user.id,
    )
    db.add(revision)
    db.flush()
    if asset_kind == "audio":
        capabilities = LongInterviewAudioIngestionAdapter.capability_keys
    elif asset_kind == "video":
        capabilities = CoreVideoIngestionAdapter.capability_keys
    else:
        capabilities = document_capabilities(asset_kind)
    job = get_ingestion_orchestrator().ensure_job(
        db,
        tenant_id=current_user.tenant_id,
        asset_revision_id=revision.id,
        capabilities=capabilities,
        idempotency_key=idempotency_key,
    )
    db.commit()
    db.refresh(asset)
    return {
        **_asset_dict(db, asset),
        "deduplicated": False,
        "capability_plan": _job_dict(job),
    }


def _dispatch_retry(
    db: Session, asset: SourceAsset, revision: AssetRevision, job: IngestionJob
) -> None:
    from app.services.ingestion_dispatch import dispatch_ingestion_job

    # Keep the compatibility signature while centralising routing for manual
    # retry and automatic stale-job recovery.
    if revision.id != job.asset_revision_id or asset.id != revision.asset_id:
        raise RuntimeError("retry dispatch asset lineage does not match")
    dispatch_ingestion_job(db, job)


@router.post("/{asset_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def retry_asset(
    asset_id: UUID,
    db: Annotated[Session, Depends(deps.get_db)],
    current_user: Annotated[User, Depends(deps.get_current_active_user)],
) -> dict[str, Any]:
    check_document_permission(current_user, "create")
    asset = _visible_asset(
        db,
        asset_id=asset_id,
        authz=AuthorizationContext.from_user(current_user),
    )
    if int(asset.current_revision or 0) == 0:
        if asset.source_system != "web" or asset.status != "failed":
            raise HTTPException(
                status_code=409, detail="asset has no retryable revision"
            )
        document = (
            db.query(Document)
            .filter(
                Document.tenant_id == asset.tenant_id,
                Document.source_asset_id == asset.id,
                Document.tombstoned_at.is_(None),
            )
            .first()
        )
        if document is None:
            raise HTTPException(status_code=409, detail="URL projection is unavailable")
        asset.status = "processing"
        document.status = "pending"
        document.error_message = None
        db.commit()
        try:
            from app.tasks.document_tasks import process_url_task

            process_url_task.delay(
                str(document.id), str(document.file_path), str(asset.tenant_id)
            )
        except Exception as exc:
            asset.status = "failed"
            document.status = "failed"
            document.error_message = "background processing could not be dispatched"
            db.commit()
            raise HTTPException(
                status_code=503, detail="retry could not be dispatched"
            ) from exc
        return {"asset_id": str(asset.id), "job": None, "dispatched": True}
    revision = (
        db.query(AssetRevision)
        .filter(
            AssetRevision.tenant_id == asset.tenant_id,
            AssetRevision.asset_id == asset.id,
            AssetRevision.revision == asset.current_revision,
        )
        .one()
    )
    job = (
        db.query(IngestionJob)
        .filter(
            IngestionJob.tenant_id == asset.tenant_id,
            IngestionJob.asset_revision_id == revision.id,
        )
        .order_by(IngestionJob.created_at.desc())
        .first()
    )
    if job is None or job.status != "failed":
        raise HTTPException(status_code=409, detail="only failed ingestion can retry")
    job = get_ingestion_orchestrator().transition(
        db, job, to_status="running", phase="retry_queued", error={}
    )
    asset.status = "processing"
    revision.ingestion_status = "processing"
    db.commit()
    try:
        _dispatch_retry(db, asset, revision, job)
    except Exception as exc:
        logger.exception("retry dispatch failed: asset=%s job=%s", asset.id, job.id)
        job = get_ingestion_orchestrator().fail(
            db,
            job,
            code="broker_dispatch_failed",
            message=str(exc),
            phase="retry_dispatch",
        )
        asset.status = "failed"
        revision.ingestion_status = "failed"
        db.commit()
        raise HTTPException(
            status_code=503, detail="retry could not be dispatched"
        ) from exc
    return {"asset_id": str(asset.id), "job": _job_dict(job), "dispatched": True}


@router.delete("/{asset_id}")
def tombstone_asset(
    asset_id: UUID,
    db: Annotated[Session, Depends(deps.get_db)],
    current_user: Annotated[User, Depends(deps.get_current_active_user)],
) -> dict[str, Any]:
    check_document_permission(current_user, "delete")
    asset = _visible_asset(
        db,
        asset_id=asset_id,
        authz=AuthorizationContext.from_user(current_user),
    )
    from datetime import datetime, timezone

    asset.tombstoned_at = datetime.now(timezone.utc)
    asset.status = "tombstoned"
    jobs = (
        db.query(IngestionJob)
        .join(
            AssetRevision,
            (AssetRevision.tenant_id == IngestionJob.tenant_id)
            & (AssetRevision.id == IngestionJob.asset_revision_id),
        )
        .filter(
            IngestionJob.tenant_id == asset.tenant_id,
            AssetRevision.asset_id == asset.id,
            IngestionJob.status.in_(["queued", "running", "failed", "review_required"]),
        )
        .all()
    )
    for job in jobs:
        if job.status != "cancelled":
            get_ingestion_orchestrator().transition(
                db, job, to_status="cancelled", phase="asset_tombstoned"
            )
    db.commit()
    return {"asset_id": str(asset.id), "status": "tombstoned"}


@router.get("/{asset_id}/events")
def list_asset_events(
    asset_id: UUID,
    db: Annotated[Session, Depends(deps.get_db)],
    current_user: Annotated[User, Depends(deps.get_current_active_user)],
) -> list[dict[str, Any]]:
    asset = _visible_asset(
        db,
        asset_id=asset_id,
        authz=AuthorizationContext.from_user(current_user),
    )
    revision_ids = [
        row[0]
        for row in db.query(AssetRevision.id).filter(
            AssetRevision.tenant_id == asset.tenant_id,
            AssetRevision.asset_id == asset.id,
        )
    ]
    rows = (
        db.query(IngestionJobEvent, IngestionJob)
        .join(
            IngestionJob,
            (IngestionJob.tenant_id == IngestionJobEvent.tenant_id)
            & (IngestionJob.id == IngestionJobEvent.job_id),
        )
        .filter(
            IngestionJobEvent.tenant_id == asset.tenant_id,
            IngestionJob.asset_revision_id.in_(revision_ids),
        )
        .order_by(IngestionJobEvent.created_at)
        .all()
    )
    return [
        {
            "id": str(event.id),
            "job_id": str(job.id),
            "sequence": event.sequence,
            "from_status": event.from_status,
            "to_status": event.to_status,
            "phase": event.phase,
            "details": dict(event.details or {}),
            "created_at": event.created_at,
        }
        for event, job in rows
    ]
