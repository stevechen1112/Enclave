"""Capability-routed worker for governed video ingestion."""

from __future__ import annotations

import logging
import os
import tempfile
import uuid
from pathlib import Path
from uuid import UUID

from app.celery_app import celery_app
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


@celery_app.task(name="tasks.process_video_asset", bind=True, max_retries=2)
def process_video_asset(self, tenant_id: str, revision_id: str, job_id: str):
    db = SessionLocal()
    tenant_uuid = UUID(tenant_id)
    revision_uuid = UUID(revision_id)
    job_uuid = UUID(job_id)
    try:
        from app.models.asset import AssetRevision, SourceAsset
        from app.models.ingestion import IngestionJob
        from app.services.ingestion_orchestrator import get_ingestion_orchestrator
        from app.services.rls import apply_rls_context

        apply_rls_context(db, tenant_uuid)
        revision = (
            db.query(AssetRevision)
            .filter(
                AssetRevision.tenant_id == tenant_uuid,
                AssetRevision.id == revision_uuid,
            )
            .one()
        )
        asset = (
            db.query(SourceAsset)
            .filter(
                SourceAsset.tenant_id == tenant_uuid,
                SourceAsset.id == revision.asset_id,
            )
            .one()
        )
        job = (
            db.query(IngestionJob)
            .filter(IngestionJob.tenant_id == tenant_uuid, IngestionJob.id == job_uuid)
            .one()
        )
        if job.status in {"review_required", "ready"}:
            return {"job_id": job_id, "status": job.status, "idempotent": True}

        orchestrator = get_ingestion_orchestrator()
        orchestrator.transition(db, job, to_status="running", phase="video_processing")
        revision.ingestion_status = "processing"
        db.commit()

        from app.services.storage import build_storage_key, get_storage_backend
        from app.services.video_processing import (
            VideoPolicyError,
            process_video_file,
            project_video_result,
        )

        backend = get_storage_backend()
        with tempfile.TemporaryDirectory(prefix="enclave-video-") as temp_dir:
            suffix = Path(
                str((revision.metadata_json or {}).get("filename") or ".mp4")
            ).suffix
            local_video = str(Path(temp_dir) / f"source{suffix or '.mp4'}")
            storage_key = str((revision.metadata_json or {}).get("storage_key") or "")
            if os.path.isfile(revision.content_uri):
                local_video = revision.content_uri
            elif storage_key:
                backend.get_to_file(storage_key, local_video)
            else:
                raise VideoPolicyError("video storage identity is unavailable")

            result = process_video_file(local_video, temp_dir)
            expected_probe = dict((revision.metadata_json or {}).get("probe") or {})
            if expected_probe and (
                expected_probe.get("video_codec") != result.probe.video_codec
                or abs(
                    int(expected_probe.get("duration_ms") or 0)
                    - result.probe.duration_ms
                )
                > 1000
            ):
                raise VideoPolicyError("worker probe differs from accepted upload")

            for keyframe in result.keyframes:
                object_id = uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"enclave:{revision.id}:keyframe:{keyframe.timestamp_ms}",
                )
                key = build_storage_key(tenant_uuid, object_id, ".jpg")
                keyframe.artifact_uri = backend.put(key, keyframe.path)
                keyframe.storage_key = key

            projection = project_video_result(
                db, revision, result, create_procedure_candidate=False
            )
            from app.services.video_understanding import (
                analyze_multimodal_timeline,
                project_multimodal_timeline,
            )

            understanding = analyze_multimodal_timeline(local_video, result)
            projection.update(project_multimodal_timeline(db, revision, understanding))
            from app.services.video_governance import (
                project_governed_video_procedure,
            )

            projection.update(project_governed_video_procedure(db, revision))

        if not projection.get("procedure_artifact_id"):
            revision.ingestion_status = "ready"
            asset.status = "active"
            orchestrator.transition(
                db,
                job,
                to_status="ready",
                phase="completed_no_knowledge",
                quality_state="rejected",
                readiness={
                    "searchable": False,
                    "requires_human_review": False,
                    "reason": "no_evidence_backed_procedure_candidate",
                    **projection,
                },
            )
            db.commit()
            return {"job_id": job_id, "status": job.status, **projection}

        revision.ingestion_status = "review_required"
        asset.status = "review_required"
        orchestrator.transition(
            db,
            job,
            to_status="review_required",
            phase="human_review",
            quality_state="review_required",
            readiness={
                "searchable": False,
                "requires_human_review": True,
                **projection,
            },
        )
        db.commit()
        return {"job_id": job_id, "status": job.status, **projection}
    except Exception as exc:
        db.rollback()
        logger.exception("video processing failed: revision=%s", revision_id)
        try:
            from app.models.asset import AssetRevision, SourceAsset
            from app.models.ingestion import IngestionJob
            from app.services.ingestion_orchestrator import get_ingestion_orchestrator
            from app.services.rls import apply_rls_context

            apply_rls_context(db, tenant_uuid)
            job = (
                db.query(IngestionJob)
                .filter(
                    IngestionJob.tenant_id == tenant_uuid,
                    IngestionJob.id == job_uuid,
                )
                .first()
            )
            revision = (
                db.query(AssetRevision)
                .filter(
                    AssetRevision.tenant_id == tenant_uuid,
                    AssetRevision.id == revision_uuid,
                )
                .first()
            )
            if job is not None and job.status in {"queued", "running"}:
                if job.status == "queued":
                    get_ingestion_orchestrator().transition(
                        db, job, to_status="running", phase="video_processing"
                    )
                get_ingestion_orchestrator().fail(
                    db,
                    job,
                    code="video_processing_failed",
                    message=str(exc),
                    phase="video_processing",
                )
            exhausted = self.request.retries >= self.max_retries
            if revision is not None:
                revision.ingestion_status = "failed" if exhausted else "pending"
                asset = (
                    db.query(SourceAsset)
                    .filter(
                        SourceAsset.tenant_id == tenant_uuid,
                        SourceAsset.id == revision.asset_id,
                    )
                    .first()
                )
                if asset is not None:
                    asset.status = "failed" if exhausted else "pending"
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("failed to persist video task failure state")
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))
        raise
    finally:
        db.close()
