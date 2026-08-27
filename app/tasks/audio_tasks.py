"""Base-pack worker for long-form audio knowledge assets."""

from __future__ import annotations

import hashlib
import logging
from uuid import UUID

from app.celery_app import celery_app
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


@celery_app.task(name="tasks.process_audio_asset", bind=True, max_retries=2)
def process_audio_asset(self, tenant_id: str, revision_id: str, job_id: str):
    db = SessionLocal()
    tenant_uuid = UUID(tenant_id)
    revision_uuid = UUID(revision_id)
    job_uuid = UUID(job_id)
    try:
        from app.models.asset import (
            AssetRevision,
            DerivedArtifact,
            EvidenceSpan,
            SourceAsset,
        )
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
        if job.status in {"queued", "failed"}:
            orchestrator.transition(db, job, to_status="running", phase="transcribing")
        revision.ingestion_status = "processing"
        db.commit()

        from app.services.storage import get_storage_backend
        from app.services.voice_gateway import transcribe_long_interview_chunk

        storage_key = str((asset.metadata_json or {}).get("storage_key") or "")
        if not storage_key:
            raise RuntimeError("audio storage identity is unavailable")
        audio_data = get_storage_backend().get_bytes(storage_key)
        result = transcribe_long_interview_chunk(
            audio_data,
            filename=str((asset.metadata_json or {}).get("filename") or "audio.webm"),
            content_type=revision.media_type,
        )
        segments = list(result.segments or [])
        if not segments and result.text.strip():
            segments = [
                {
                    "start": 0,
                    "end": max(float(result.duration_seconds or 0), 0.001),
                    "text": result.text,
                    "speaker": None,
                }
            ]
        if not segments:
            raise RuntimeError("transcription returned no usable content")

        artifact_ids: list[str] = []
        for sequence, segment in enumerate(segments, start=1):
            text = str(segment.get("text") or "").strip()
            if not text:
                continue
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            artifact = (
                db.query(DerivedArtifact)
                .filter(
                    DerivedArtifact.tenant_id == tenant_uuid,
                    DerivedArtifact.asset_revision_id == revision.id,
                    DerivedArtifact.artifact_kind == "transcript_segment",
                    DerivedArtifact.provider == "openai",
                    DerivedArtifact.provider_version == "long_interview_stt",
                    DerivedArtifact.content_hash == digest,
                )
                .first()
            )
            if artifact is None:
                artifact = DerivedArtifact(
                    tenant_id=tenant_uuid,
                    asset_revision_id=revision.id,
                    artifact_kind="transcript_segment",
                    content_hash=digest,
                    provider="openai",
                    provider_version="long_interview_stt",
                    quality_state="review_required",
                    confidence=result.confidence if result.confidence > 0 else None,
                    content=text,
                    metadata_json={"sequence": sequence, "language": result.language},
                )
                db.add(artifact)
                db.flush()
            start_ms = max(0, int(float(segment.get("start") or 0) * 1000))
            end_ms = max(start_ms + 1, int(float(segment.get("end") or 0) * 1000))
            span = (
                db.query(EvidenceSpan.id)
                .filter(
                    EvidenceSpan.tenant_id == tenant_uuid,
                    EvidenceSpan.artifact_id == artifact.id,
                    EvidenceSpan.start_ms == start_ms,
                    EvidenceSpan.end_ms == end_ms,
                )
                .first()
            )
            if span is None:
                db.add(
                    EvidenceSpan(
                        tenant_id=tenant_uuid,
                        artifact_id=artifact.id,
                        asset_revision_id=revision.id,
                        locator_kind="audio",
                        start_ms=start_ms,
                        end_ms=end_ms,
                        speaker=segment.get("speaker"),
                    )
                )
            artifact_ids.append(str(artifact.id))

        if not artifact_ids:
            raise RuntimeError("transcription contained only empty segments")
        revision.duration_ms = max(1, int(float(result.duration_seconds or 0) * 1000))
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
                "artifact_ids": artifact_ids,
            },
        )
        db.commit()
        return {"job_id": job_id, "status": job.status, "artifact_ids": artifact_ids}
    except Exception as exc:
        db.rollback()
        logger.exception("audio processing failed: revision=%s", revision_id)
        try:
            from app.models.asset import AssetRevision, SourceAsset
            from app.models.ingestion import IngestionJob
            from app.services.ingestion_orchestrator import get_ingestion_orchestrator
            from app.services.rls import apply_rls_context

            apply_rls_context(db, tenant_uuid)
            job = (
                db.query(IngestionJob)
                .filter(
                    IngestionJob.tenant_id == tenant_uuid, IngestionJob.id == job_uuid
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
                        db, job, to_status="running", phase="transcribing"
                    )
                get_ingestion_orchestrator().fail(
                    db,
                    job,
                    code="audio_processing_failed",
                    message=str(exc),
                    phase="transcribing",
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
                    asset.status = "failed" if exhausted else "processing"
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("failed to persist audio task failure state")
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))
        raise
    finally:
        db.close()
