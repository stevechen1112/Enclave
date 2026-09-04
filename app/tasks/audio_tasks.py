"""Resumable, bounded worker for long-form audio knowledge assets."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path
from uuid import UUID

from app.celery_app import celery_app
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


def _segment_digest(
    *, text: str, start_ms: int, end_ms: int, speaker: str | None
) -> str:
    payload = json.dumps(
        [text, start_ms, end_ms, speaker], ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@celery_app.task(
    name="tasks.process_audio_asset",
    bind=True,
    max_retries=2,
    acks_late=True,
    soft_time_limit=1500,
    time_limit=1800,
)
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
            orchestrator.transition(db, job, to_status="running", phase="audio_probe")
        revision.ingestion_status = "processing"
        db.commit()

        from app.config import settings
        from app.services.media_productization import (
            create_browser_audio_proxy,
            extract_audio_chunks,
            probe_audio,
        )
        from app.services.storage import build_storage_key, get_storage_backend
        from app.services.video_processing import project_media_proxy
        from app.services.voice_gateway import transcribe_long_interview_chunk
        from app.services.input_capability_results import (
            audio_capability_results,
            package_version,
            readiness_with_capability_results,
        )
        from app.services.input_quality import normalize_provider_confidence

        metadata = dict(revision.metadata_json or {})
        storage_key = str(metadata.get("storage_key") or "")
        if not storage_key and not os.path.isfile(revision.content_uri):
            raise RuntimeError("audio storage identity is unavailable")

        backend = get_storage_backend()
        # A retry may start after earlier chunks were committed. Terminal truth
        # must include those persisted segments, not only this attempt's output.
        artifact_ids: list[str] = [
            str(row.id)
            for row in db.query(DerivedArtifact.id)
            .filter(
                DerivedArtifact.tenant_id == tenant_uuid,
                DerivedArtifact.asset_revision_id == revision.id,
                DerivedArtifact.artifact_kind == "transcript_segment",
                DerivedArtifact.provider == "openai",
                DerivedArtifact.provider_version == "long_interview_stt.i5",
            )
            .all()
        ]
        with tempfile.TemporaryDirectory(prefix="enclave-audio-") as temp_dir:
            suffix = Path(str(metadata.get("filename") or ".webm")).suffix or ".webm"
            local_audio = str(Path(temp_dir) / f"source{suffix}")
            if os.path.isfile(revision.content_uri):
                local_audio = revision.content_uri
            else:
                backend.get_to_file(storage_key, local_audio)

            probe = probe_audio(local_audio)
            revision.duration_ms = probe.duration_ms
            if settings.MEDIA_PROXY_ENABLED:
                from uuid import NAMESPACE_URL, uuid5

                proxy_path = str(Path(temp_dir) / "review-proxy.mp3")
                create_browser_audio_proxy(local_audio, proxy_path)
                proxy_object_id = uuid5(
                    NAMESPACE_URL, f"enclave:{revision.id}:audio-media-proxy:v1"
                )
                proxy_key = build_storage_key(tenant_uuid, proxy_object_id, ".mp3")
                proxy_size = os.path.getsize(proxy_path)
                proxy_uri = backend.put(proxy_key, proxy_path)
                project_media_proxy(
                    db,
                    revision,
                    artifact_uri=proxy_uri,
                    storage_key=proxy_key,
                    byte_size=proxy_size,
                    media_type="audio/mpeg",
                    browser_profile="mp3_mono_44k_96k",
                )
            orchestrator.transition(
                db,
                job,
                to_status="running",
                phase="audio_chunking",
                readiness={
                    "searchable": False,
                    "partial": False,
                    "requires_human_review": False,
                    "probe": probe.to_dict(),
                    "preview_ready": bool(settings.MEDIA_PROXY_ENABLED),
                },
            )
            db.commit()

            chunks = extract_audio_chunks(
                local_audio, temp_dir, chunk_seconds=int(settings.AUDIO_CHUNK_SECONDS)
            )
            if not chunks:
                raise RuntimeError("audio chunking returned no decodable audio")

            for chunk_index, chunk_path in enumerate(chunks):
                with open(chunk_path, "rb") as stream:
                    result = transcribe_long_interview_chunk(
                        stream.read(),
                        filename=os.path.basename(chunk_path),
                        content_type="audio/mpeg",
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
                offset_ms = chunk_index * int(settings.AUDIO_CHUNK_SECONDS) * 1000
                for segment in segments:
                    text = str(segment.get("text") or "").strip()
                    if not text:
                        continue
                    start_ms = min(
                        max(
                            0, offset_ms + int(float(segment.get("start") or 0) * 1000)
                        ),
                        max(0, probe.duration_ms - 1),
                    )
                    end_ms = min(
                        probe.duration_ms,
                        max(
                            start_ms + 1,
                            offset_ms + int(float(segment.get("end") or 0) * 1000),
                        ),
                    )
                    speaker = str(segment.get("speaker") or "").strip() or None
                    digest = _segment_digest(
                        text=text, start_ms=start_ms, end_ms=end_ms, speaker=speaker
                    )
                    artifact = (
                        db.query(DerivedArtifact)
                        .filter(
                            DerivedArtifact.tenant_id == tenant_uuid,
                            DerivedArtifact.asset_revision_id == revision.id,
                            DerivedArtifact.artifact_kind == "transcript_segment",
                            DerivedArtifact.provider == "openai",
                            DerivedArtifact.provider_version == "long_interview_stt.i5",
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
                            provider_version="long_interview_stt.i5",
                            quality_state="review_required",
                            confidence=normalize_provider_confidence(
                                result.confidence,
                                provider_supplied=result.confidence_provider_supplied,
                            ),
                            content=text,
                            metadata_json={
                                "chunk_index": chunk_index,
                                "language": result.language,
                                "start_ms": start_ms,
                                "end_ms": end_ms,
                                "candidate_only": True,
                                "source_provider": result.provider or "openai",
                                "source_provider_version": (
                                    result.provider_version or package_version("openai")
                                ),
                                "source_model": (
                                    result.model or settings.LONG_INTERVIEW_STT_MODEL
                                ),
                                "confidence_semantics": (
                                    "provider_supplied"
                                    if result.confidence_provider_supplied
                                    else "unknown"
                                ),
                                "confidence_provider_supplied": (
                                    result.confidence_provider_supplied
                                ),
                                "confidence_calibration_version": (
                                    result.confidence_calibration_version
                                    or "unavailable"
                                ),
                            },
                        )
                        db.add(artifact)
                        db.flush()
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
                                speaker=speaker,
                            )
                        )
                    artifact_ids.append(str(artifact.id))

                artifact_ids = list(dict.fromkeys(artifact_ids))
                orchestrator.transition(
                    db,
                    job,
                    to_status="running",
                    phase="transcript_partial",
                    readiness={
                        "searchable": False,
                        "partial": True,
                        "requires_human_review": True,
                        "completed_chunks": chunk_index + 1,
                        "total_chunks": len(chunks),
                        "progress_percent": round(
                            (chunk_index + 1) * 100 / len(chunks), 1
                        ),
                        "artifact_ids": artifact_ids,
                    },
                    details={
                        "completed_chunks": chunk_index + 1,
                        "total_chunks": len(chunks),
                    },
                )
                db.commit()

        capability_results = audio_capability_results(
            job.requested_capabilities or [],
            transcript_count=len(artifact_ids),
            audio_chunk_count=len(chunks),
            preview_ready=bool(settings.MEDIA_PROXY_ENABLED),
            provider=(result.provider or "openai"),
            provider_version=result.provider_version,
            model=(result.model or settings.LONG_INTERVIEW_STT_MODEL),
            confidence_provider_supplied=result.confidence_provider_supplied,
            calibration_version=result.confidence_calibration_version,
        )
        if not artifact_ids:
            revision.ingestion_status = "ready"
            asset.status = "active"
            orchestrator.transition(
                db,
                job,
                to_status="ready",
                phase="completed_no_speech",
                quality_state="rejected",
                readiness=readiness_with_capability_results(
                    {
                        "searchable": False,
                        "partial": False,
                        "requires_human_review": False,
                        "reason": "no_speech_detected",
                        "artifact_ids": [],
                    },
                    requested_capabilities=job.requested_capabilities or [],
                    observed=capability_results,
                ),
            )
            db.commit()
            return {"job_id": job_id, "status": job.status, "artifact_ids": []}
        revision.ingestion_status = "review_required"
        asset.status = "review_required"
        orchestrator.transition(
            db,
            job,
            to_status="review_required",
            phase="human_review",
            quality_state="review_required",
            readiness=readiness_with_capability_results(
                {
                    "searchable": False,
                    "partial": False,
                    "requires_human_review": True,
                    "artifact_ids": artifact_ids,
                },
                requested_capabilities=job.requested_capabilities or [],
                observed=capability_results,
            ),
        )
        db.commit()
        return {"job_id": job_id, "status": job.status, "artifact_ids": artifact_ids}
    except Exception as exc:
        db.rollback()
        logger.exception("audio processing failed: revision=%s", revision_id)
        from app.services.ingestion_failures import classify_ingestion_failure

        failure = classify_ingestion_failure(exc)
        exhausted = (not failure.retryable) or self.request.retries >= self.max_retries
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
                        db, job, to_status="running", phase="audio_probe"
                    )
                get_ingestion_orchestrator().fail(
                    db,
                    job,
                    code=failure.code,
                    message=failure.technical_message,
                    phase="audio_processing",
                    category=failure.category,
                    retryable=failure.retryable,
                    user_message=failure.user_message,
                )
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
        if failure.retryable and self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))
        raise
    finally:
        db.close()
