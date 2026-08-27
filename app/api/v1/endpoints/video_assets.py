"""Tenant-scoped video upload, review timeline and publication API."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

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
from fastapi.responses import FileResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api import deps
from app.api.deps_permissions import check_document_permission
from app.config import settings
from app.core.authorization import AuthorizationContext
from app.models.asset import (
    ArtifactReviewDecision,
    AssetRevision,
    DerivedArtifact,
    EvidenceSpan,
    SourceAsset,
)
from app.models.ingestion import IngestionJob
from app.models.user import User

router = APIRouter()
logger = logging.getLogger(__name__)

_VIDEO_TYPES = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
}
_VIDEO_CAPABILITIES = (
    "probe_metadata",
    "demux_audio",
    "transcribe",
    "timestamp",
    "keyframe",
    "ocr",
    "diarize",
    "scene_segment",
    "action_candidate",
    "equipment_state",
    "audio_event",
    "temporal_align",
    "procedure_candidate",
)


class ArtifactReviewRequest(BaseModel):
    decision: str
    notes: str | None = Field(default=None, max_length=2000)
    conflict_resolutions: dict[str, str] = Field(default_factory=dict)
    acknowledge_high_risk: bool = False


def _asset_or_404(
    db: Session,
    *,
    tenant_id: UUID,
    asset_id: UUID,
    authz: AuthorizationContext | None = None,
) -> SourceAsset:
    asset = (
        db.query(SourceAsset)
        .filter(
            SourceAsset.tenant_id == tenant_id,
            SourceAsset.id == asset_id,
            SourceAsset.asset_kind == "video",
            SourceAsset.tombstoned_at.is_(None),
        )
        .first()
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="video asset not found")
    if authz is not None:
        from app.services.asset_visibility import asset_access_allows

        if not asset_access_allows(db, asset, authz=authz):
            raise HTTPException(status_code=404, detail="video asset not found")
    return asset


def _current_revision(
    db: Session, *, asset: SourceAsset, tenant_id: UUID
) -> AssetRevision:
    revision = (
        db.query(AssetRevision)
        .filter(
            AssetRevision.tenant_id == tenant_id,
            AssetRevision.asset_id == asset.id,
            AssetRevision.revision == asset.current_revision,
        )
        .first()
    )
    if revision is None:
        raise HTTPException(status_code=409, detail="video revision is unavailable")
    return revision


def _serialize_asset(db: Session, asset: SourceAsset) -> dict[str, Any]:
    revision = _current_revision(db, asset=asset, tenant_id=asset.tenant_id)
    job = (
        db.query(IngestionJob)
        .filter(
            IngestionJob.tenant_id == asset.tenant_id,
            IngestionJob.asset_revision_id == revision.id,
        )
        .order_by(IngestionJob.created_at.desc())
        .first()
    )
    return {
        "id": str(asset.id),
        "title": asset.title,
        "status": asset.status,
        "created_at": asset.created_at,
        "revision_id": str(revision.id),
        "duration_ms": revision.duration_ms,
        "media_type": revision.media_type,
        "probe": dict((revision.metadata_json or {}).get("probe") or {}),
        "job": (
            {
                "id": str(job.id),
                "status": job.status,
                "phase": job.phase,
                "quality_state": job.quality_state,
                "readiness": dict(job.readiness or {}),
                "error": dict(job.error or {}),
            }
            if job
            else None
        ),
    }


@router.get("/media/videos")
def list_video_assets(
    db: Annotated[Session, Depends(deps.get_db)],
    current_user: Annotated[User, Depends(deps.get_current_active_user)],
) -> list[dict[str, Any]]:
    from app.services.asset_visibility import asset_access_allows

    authz = AuthorizationContext.from_user(current_user)
    assets = (
        db.query(SourceAsset)
        .filter(
            SourceAsset.tenant_id == current_user.tenant_id,
            SourceAsset.asset_kind == "video",
            SourceAsset.tombstoned_at.is_(None),
        )
        .order_by(SourceAsset.created_at.desc())
        .limit(500)
        .all()
    )
    return [
        _serialize_asset(db, asset)
        for asset in assets
        if asset_access_allows(db, asset, authz=authz)
    ][:100]


@router.post("/media/videos", status_code=status.HTTP_202_ACCEPTED)
async def upload_video_asset(
    file: Annotated[UploadFile, File()],
    db: Annotated[Session, Depends(deps.get_db)],
    current_user: Annotated[User, Depends(deps.get_current_active_user)],
    title: Annotated[str | None, Form()] = None,
    equipment_ids: Annotated[str | None, Form()] = None,
    applicable_roles: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    check_document_permission(current_user, "create")
    if not settings.VIDEO_INGESTION_ENABLED:
        raise HTTPException(status_code=404, detail="video ingestion is not enabled")
    clean_filename = os.path.basename(file.filename or "")
    extension = Path(clean_filename).suffix.lower()
    if not clean_filename or extension not in _VIDEO_TYPES:
        raise HTTPException(status_code=400, detail="unsupported video container")

    descriptor, temp_path = tempfile.mkstemp(prefix="enclave-upload-", suffix=extension)
    os.close(descriptor)
    file_size = 0
    digest = hashlib.sha256()
    try:
        try:
            async with aiofiles.open(temp_path, "wb") as stream:
                while chunk := await file.read(1024 * 1024):
                    file_size += len(chunk)
                    if file_size > int(settings.VIDEO_MAX_BYTES):
                        raise HTTPException(
                            status_code=413, detail="video exceeds size limit"
                        )
                    digest.update(chunk)
                    await stream.write(chunk)
        except Exception:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise
    finally:
        await file.close()
    if file_size == 0:
        os.remove(temp_path)
        raise HTTPException(status_code=400, detail="video is empty")

    storage_key = ""
    try:
        from app.services.file_scan import scan_file_path
        from app.services.video_processing import VideoPolicyError, probe_video

        scan_file_path(temp_path, clean_filename)
        try:
            probe = probe_video(temp_path)
        except VideoPolicyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        from app.crud import crud_tenant

        storage_quota = crud_tenant.lock_and_check_storage_quota(
            db, current_user.tenant_id, file_size
        )
        if not storage_quota.get("allowed", True):
            raise HTTPException(status_code=429, detail="storage quota exceeded")

        equipment_values = [
            value.strip()[:100]
            for value in str(equipment_ids or "").split(",")
            if value.strip()
        ][:20]
        role_values = [
            value.strip()[:100]
            for value in str(applicable_roles or "").split(",")
            if value.strip()
        ][:20]
        from app.services.asset_visibility import canonical_asset_acl

        asset = SourceAsset(
            tenant_id=current_user.tenant_id,
            asset_kind="video",
            title=((title or clean_filename).strip() or clean_filename)[:500],
            source_system="upload",
            data_classification="confidential",
            acl_reference={
                **canonical_asset_acl(owner_subject_id=current_user.id),
                "uploaded_by": str(current_user.id),
            },
            metadata_json={
                "filename": clean_filename,
                "equipment_ids": equipment_values,
                "applicable_roles": role_values,
            },
            current_revision=1,
            status="pending",
            created_by=current_user.id,
            captured_by=current_user.id,
        )
        db.add(asset)
        db.flush()

        from app.services.storage import build_storage_key, get_storage_backend

        storage_key = build_storage_key(current_user.tenant_id, asset.id, extension)
        backend = get_storage_backend()
        content_uri = backend.put(storage_key, temp_path)
        revision = AssetRevision(
            tenant_id=current_user.tenant_id,
            asset_id=asset.id,
            revision=1,
            media_type=_VIDEO_TYPES[extension],
            content_uri=content_uri,
            content_hash=digest.hexdigest(),
            byte_size=file_size,
            duration_ms=probe.duration_ms,
            ingestion_status="pending",
            metadata_json={
                "filename": clean_filename,
                "storage_key": storage_key,
                "probe": probe.to_dict(),
            },
            created_by=current_user.id,
        )
        db.add(revision)
        db.flush()

        from app.services.ingestion_orchestrator import get_ingestion_orchestrator

        job = get_ingestion_orchestrator().ensure_job(
            db,
            tenant_id=current_user.tenant_id,
            asset_revision_id=revision.id,
            capabilities=_VIDEO_CAPABILITIES,
            idempotency_key=f"video:{revision.id}:v1",
        )
        db.commit()
    except HTTPException:
        db.rollback()
        if storage_key:
            try:
                get_storage_backend().delete(storage_key)
            except Exception:
                logger.exception("failed to clean rejected video object")
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise
    except Exception:
        db.rollback()
        if storage_key:
            try:
                from app.services.storage import get_storage_backend

                get_storage_backend().delete(storage_key)
            except Exception:
                logger.exception("failed to clean video object after upload error")
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise

    dispatched = True
    try:
        from app.tasks.video_tasks import process_video_asset

        process_video_asset.delay(
            str(current_user.tenant_id), str(revision.id), str(job.id)
        )
    except Exception:
        dispatched = False
        logger.exception("video job persisted but broker dispatch failed: %s", job.id)
    return {**_serialize_asset(db, asset), "dispatched": dispatched}


@router.get("/media/videos/{asset_id}")
def get_video_review(
    asset_id: UUID,
    db: Annotated[Session, Depends(deps.get_db)],
    current_user: Annotated[User, Depends(deps.get_current_active_user)],
) -> dict[str, Any]:
    authz = AuthorizationContext.from_user(current_user)
    asset = _asset_or_404(
        db,
        tenant_id=current_user.tenant_id,
        asset_id=asset_id,
        authz=authz,
    )
    revision = _current_revision(db, asset=asset, tenant_id=current_user.tenant_id)
    artifacts = (
        db.query(DerivedArtifact)
        .filter(
            DerivedArtifact.tenant_id == current_user.tenant_id,
            DerivedArtifact.asset_revision_id == revision.id,
        )
        .order_by(DerivedArtifact.created_at.asc())
        .all()
    )
    artifact_ids = [artifact.id for artifact in artifacts]
    evidence_rows = (
        db.query(EvidenceSpan)
        .filter(
            EvidenceSpan.tenant_id == current_user.tenant_id,
            EvidenceSpan.asset_revision_id == revision.id,
            EvidenceSpan.artifact_id.in_(artifact_ids),
        )
        .all()
        if artifact_ids
        else []
    )
    evidence_by_artifact: dict[UUID, list[dict[str, Any]]] = {}
    for evidence in evidence_rows:
        evidence_by_artifact.setdefault(evidence.artifact_id, []).append(
            {
                "id": str(evidence.id),
                "locator_kind": evidence.locator_kind,
                "start_ms": evidence.start_ms,
                "end_ms": evidence.end_ms,
                "frame_index": evidence.frame_index,
                "speaker": evidence.speaker,
                "deep_link": f"/knowledge/videos/{asset.id}?t={evidence.start_ms or 0}",
            }
        )
    decisions = {
        decision.artifact_id: decision
        for decision in db.query(ArtifactReviewDecision)
        .filter(
            ArtifactReviewDecision.tenant_id == current_user.tenant_id,
            ArtifactReviewDecision.asset_revision_id == revision.id,
        )
        .all()
    }
    from app.services.media_access import create_media_token

    rows = []
    for artifact in artifacts:
        decision = decisions.get(artifact.id)
        content: Any = artifact.content
        if artifact.artifact_kind in {
            "procedure_candidate",
            "timeline_alignment",
            "sop_conflict_report",
        } and artifact.content:
            try:
                content = json.loads(artifact.content)
            except ValueError:
                content = {"raw": artifact.content}
        rows.append(
            {
                "id": str(artifact.id),
                "kind": artifact.artifact_kind,
                "quality_state": artifact.quality_state,
                "confidence": artifact.confidence,
                "content": content,
                "metadata": dict(artifact.metadata_json or {}),
                "content_url": (
                    f"/api/v1/media/video-artifacts/{artifact.id}/content?token="
                    + create_media_token(
                        tenant_id=current_user.tenant_id,
                        user_id=current_user.id,
                        resource_kind="video_artifact",
                        resource_id=artifact.id,
                    )
                    if artifact.artifact_uri
                    else None
                ),
                "evidence": evidence_by_artifact.get(artifact.id, []),
                "review": (
                    {
                        "decision": decision.decision,
                        "notes": decision.notes,
                        "reviewer_id": str(decision.reviewer_id),
                        "created_at": decision.created_at,
                        "resolution": dict(decision.resolution_json or {}),
                    }
                    if decision
                    else None
                ),
            }
        )
    return {
        **_serialize_asset(db, asset),
        "content_url": (
            f"/api/v1/media/videos/{asset.id}/content?token="
            + create_media_token(
                tenant_id=current_user.tenant_id,
                user_id=current_user.id,
                resource_kind="video",
                resource_id=asset.id,
            )
        ),
        "artifacts": rows,
    }


def _object_response(
    *, storage_key: str, local_uri: str | None, filename: str, media_type: str
) -> FileResponse | RedirectResponse:
    from app.services.storage import get_storage_backend

    backend = get_storage_backend()
    if backend.name == "local" and local_uri and os.path.isfile(local_uri):
        return FileResponse(
            local_uri,
            filename=filename,
            media_type=media_type,
            content_disposition_type="inline",
        )
    if not storage_key:
        raise HTTPException(status_code=409, detail="media object is unavailable")
    return RedirectResponse(
        backend.presigned_url(storage_key, expires=900), status_code=307
    )


def _media_token_authz(
    db: Session, *, claims: dict[str, Any], tenant_id: UUID
) -> AuthorizationContext:
    try:
        subject_id = UUID(str(claims["sub"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=403, detail="invalid media token") from exc
    user = (
        db.query(User)
        .filter(
            User.tenant_id == tenant_id,
            User.id == subject_id,
            User.status == "active",
        )
        .first()
    )
    if user is None:
        raise HTTPException(status_code=403, detail="media token subject is unavailable")
    return AuthorizationContext.from_user(user)


@router.get("/media/videos/{asset_id}/content")
def get_video_content(
    asset_id: UUID,
    db: Annotated[Session, Depends(deps.get_db)],
    token: Annotated[str, Query(min_length=1)],
) -> Response:
    from app.services.media_access import decode_media_token
    from app.services.rls import apply_rls_context

    claims = decode_media_token(token, resource_kind="video", resource_id=asset_id)
    if claims is None:
        raise HTTPException(status_code=403, detail="invalid or expired media token")
    try:
        tenant_id = UUID(str(claims["tenant_id"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=403, detail="invalid media token") from exc
    apply_rls_context(db, tenant_id)
    authz = _media_token_authz(db, claims=claims, tenant_id=tenant_id)
    asset = _asset_or_404(
        db, tenant_id=tenant_id, asset_id=asset_id, authz=authz
    )
    revision = _current_revision(db, asset=asset, tenant_id=tenant_id)
    metadata = dict(revision.metadata_json or {})
    return _object_response(
        storage_key=str(metadata.get("storage_key") or ""),
        local_uri=revision.content_uri,
        filename=str(metadata.get("filename") or f"{asset.id}.mp4"),
        media_type=revision.media_type,
    )


@router.get("/media/video-artifacts/{artifact_id}/content")
def get_video_artifact_content(
    artifact_id: UUID,
    db: Annotated[Session, Depends(deps.get_db)],
    token: Annotated[str, Query(min_length=1)],
) -> Response:
    from app.services.media_access import decode_media_token
    from app.services.rls import apply_rls_context

    claims = decode_media_token(
        token, resource_kind="video_artifact", resource_id=artifact_id
    )
    if claims is None:
        raise HTTPException(status_code=403, detail="invalid or expired media token")
    try:
        tenant_id = UUID(str(claims["tenant_id"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=403, detail="invalid media token") from exc
    apply_rls_context(db, tenant_id)
    row = (
        db.query(DerivedArtifact, AssetRevision, SourceAsset)
        .join(
            AssetRevision,
            (AssetRevision.tenant_id == DerivedArtifact.tenant_id)
            & (AssetRevision.id == DerivedArtifact.asset_revision_id),
        )
        .join(
            SourceAsset,
            (SourceAsset.tenant_id == AssetRevision.tenant_id)
            & (SourceAsset.id == AssetRevision.asset_id),
        )
        .filter(
            DerivedArtifact.tenant_id == tenant_id,
            DerivedArtifact.id == artifact_id,
            DerivedArtifact.artifact_kind == "keyframe",
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="video artifact not found")
    artifact, _revision, asset = row
    authz = _media_token_authz(db, claims=claims, tenant_id=tenant_id)
    from app.services.asset_visibility import asset_access_allows

    if not asset_access_allows(db, asset, authz=authz):
        raise HTTPException(status_code=404, detail="video artifact not found")
    metadata = dict(artifact.metadata_json or {})
    return _object_response(
        storage_key=str(metadata.get("storage_key") or ""),
        local_uri=artifact.artifact_uri,
        filename=f"{artifact.id}.jpg",
        media_type="image/jpeg",
    )


@router.post("/media/video-artifacts/{artifact_id}/review")
def review_video_procedure(
    artifact_id: UUID,
    request: ArtifactReviewRequest,
    db: Annotated[Session, Depends(deps.get_db)],
    current_user: Annotated[User, Depends(deps.get_current_active_user)],
) -> dict[str, Any]:
    if not (current_user.is_superuser or current_user.role in {"owner", "admin"}):
        raise HTTPException(status_code=403, detail="review permission required")
    if request.decision not in {"approved", "rejected"}:
        raise HTTPException(status_code=400, detail="invalid review decision")
    artifact = (
        db.query(DerivedArtifact)
        .filter(
            DerivedArtifact.tenant_id == current_user.tenant_id,
            DerivedArtifact.id == artifact_id,
            DerivedArtifact.artifact_kind == "procedure_candidate",
        )
        .with_for_update()
        .first()
    )
    if artifact is None:
        raise HTTPException(status_code=404, detail="procedure candidate not found")
    revision = (
        db.query(AssetRevision)
        .filter(
            AssetRevision.tenant_id == current_user.tenant_id,
            AssetRevision.id == artifact.asset_revision_id,
        )
        .one()
    )
    asset = _asset_or_404(
        db,
        tenant_id=current_user.tenant_id,
        asset_id=revision.asset_id,
        authz=AuthorizationContext.from_user(current_user),
    )
    existing = (
        db.query(ArtifactReviewDecision)
        .filter(
            ArtifactReviewDecision.tenant_id == current_user.tenant_id,
            ArtifactReviewDecision.artifact_id == artifact.id,
        )
        .first()
    )
    if existing is not None:
        if existing.decision != request.decision:
            raise HTTPException(status_code=409, detail="artifact already reviewed")
        return {"artifact_id": str(artifact.id), "decision": existing.decision}
    if artifact.quality_state != "review_required":
        raise HTTPException(status_code=409, detail="artifact is not reviewable")

    try:
        procedure_payload = json.loads(artifact.content or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=409, detail="procedure payload is invalid") from exc
    conflict_artifacts = (
        db.query(DerivedArtifact)
        .filter(
            DerivedArtifact.tenant_id == current_user.tenant_id,
            DerivedArtifact.asset_revision_id == artifact.asset_revision_id,
            DerivedArtifact.artifact_kind == "sop_conflict_report",
        )
        .order_by(DerivedArtifact.created_at.desc())
        .all()
    )
    conflict_artifact = next(
        (
            row
            for row in conflict_artifacts
            if str((row.metadata_json or {}).get("procedure_artifact_id") or "")
            == str(artifact.id)
        ),
        None,
    )
    conflict_report: dict[str, Any] = {"conflicts": []}
    if conflict_artifact is not None:
        try:
            conflict_report = json.loads(conflict_artifact.content or "{}")
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=409, detail="SOP conflict report is invalid") from exc

    resolution_json: dict[str, Any] = {}
    approved = request.decision == "approved"
    if approved:
        high_risk = bool(
            (artifact.metadata_json or {}).get("high_risk")
            or procedure_payload.get("risks")
            or procedure_payload.get("prohibited_actions")
        )
        if high_risk and not request.acknowledge_high_risk:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "high_risk_acknowledgement_required",
                    "message": "high-risk procedure requires explicit acknowledgement",
                },
            )
        from app.services.video_governance import apply_sop_precedence

        known_conflict_ids = {
            str(row.get("id") or "")
            for row in list(conflict_report.get("conflicts") or [])
        }
        unknown_resolutions = set(request.conflict_resolutions) - known_conflict_ids
        if unknown_resolutions:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "unknown_sop_conflict",
                    "conflict_ids": sorted(unknown_resolutions),
                },
            )
        published_procedure, unresolved = apply_sop_precedence(
            procedure_payload,
            list(conflict_report.get("conflicts") or []),
            request.conflict_resolutions,
        )
        if unresolved:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "unresolved_sop_conflicts",
                    "message": "all SOP conflicts must resolve with formal SOP precedence",
                    "conflict_ids": unresolved,
                },
            )
        resolution_json = {
            "conflict_resolutions": dict(request.conflict_resolutions),
            "published_procedure": published_procedure,
            "acknowledged_high_risk": high_risk,
            "conflict_report_artifact_id": (
                str(conflict_artifact.id) if conflict_artifact is not None else None
            ),
        }
        from app.services.knowledge_authority import (
            publish_approved_video_procedure,
        )

        resolution_json["knowledge_authority"] = publish_approved_video_procedure(
            db,
            asset=asset,
            asset_revision=revision,
            artifact=artifact,
            published_procedure=published_procedure,
            reviewer_id=current_user.id,
            high_risk=high_risk,
        )

    decision = ArtifactReviewDecision(
        tenant_id=current_user.tenant_id,
        artifact_id=artifact.id,
        asset_revision_id=artifact.asset_revision_id,
        decision=request.decision,
        notes=request.notes,
        reviewer_id=current_user.id,
        resolution_json=resolution_json,
    )
    db.add(decision)
    artifact.quality_state = "ready" if approved else "rejected"
    if conflict_artifact is not None:
        conflict_artifact.quality_state = "ready" if approved else "rejected"
    job = (
        db.query(IngestionJob)
        .filter(
            IngestionJob.tenant_id == current_user.tenant_id,
            IngestionJob.asset_revision_id == revision.id,
            IngestionJob.status == "review_required",
        )
        .with_for_update()
        .first()
    )
    if job is None:
        raise HTTPException(status_code=409, detail="review job is unavailable")
    from app.services.ingestion_orchestrator import get_ingestion_orchestrator

    get_ingestion_orchestrator().transition(
        db,
        job,
        to_status="ready",
        phase="published" if approved else "review_rejected",
        quality_state="ready" if approved else "rejected",
        readiness={
            "searchable": approved,
            "procedure_artifact_id": str(artifact.id),
            "reviewed_by": str(current_user.id),
        },
    )
    revision.ingestion_status = "ready"
    asset.status = "active"
    db.commit()
    return {
        "artifact_id": str(artifact.id),
        "decision": request.decision,
        "quality_state": artifact.quality_state,
        "searchable": approved,
    }
