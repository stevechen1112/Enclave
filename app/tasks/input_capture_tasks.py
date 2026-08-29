"""Core Input background tasks for capture transcription and retention."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from app.celery_app import celery_app
from app.db.session import MaintenanceSessionLocal, SessionLocal

logger = logging.getLogger(__name__)


@celery_app.task(name="tasks.purge_mka_retention", bind=True, max_retries=2)
def purge_mka_retention(self):
    """硬刪過期語音轉寫 session；回傳刪除統計供 audit。"""
    db = MaintenanceSessionLocal()
    try:
        from app.services.rls import apply_rls_bypass

        apply_rls_bypass(
            db,
            actor_identity="celery:purge_mka_retention",
            operation="purge_mka_retention",
            reason="Apply configured cross-tenant retention policies",
            correlation_id=str(getattr(self.request, "id", "") or "") or None,
        )
        from app.services.audio_retention import (
            purge_expired_knowledge_captures,
            purge_expired_transcripts,
        )

        result = purge_expired_transcripts(db)
        result.update(purge_expired_knowledge_captures(db))
        db.commit()
        logger.info("purge_mka_retention done: %s", result)
        return result
    except Exception as exc:
        db.rollback()
        logger.exception("purge_mka_retention failed")
        raise self.retry(exc=exc, countdown=300)
    finally:
        db.close()


@celery_app.task(name="tasks.transcribe_knowledge_capture", bind=True, max_retries=2)
def transcribe_knowledge_capture(self, tenant_id: str, session_id: str):
    """Transcribe durable interview chunks after recording has completed.

    The worker reads each tenant-scoped object through StorageBackend and writes
    per-chunk transcript segments.  It never runs in the browser request, so a
    30–60 minute interview cannot time out the user's phone connection.
    """
    db = SessionLocal()
    ingestion_job_id = None
    try:
        from app.config import settings
        from app.models.mka import (
            KnowledgeCaptureChunk,
            KnowledgeCaptureSession,
            KnowledgeCaptureTranscriptSegment,
        )
        from app.models.user import User
        from app.services.audio_retention import record_cost_db
        from app.services.rls import apply_rls_context
        from app.services.storage import get_storage_backend
        from app.services.term_dictionary import get_term_dictionary_service
        from app.services.voice_gateway import transcribe_long_interview_chunk

        tenant_uuid = UUID(tenant_id)
        capture_uuid = UUID(session_id)
        apply_rls_context(db, tenant_uuid)
        capture = (
            db.query(KnowledgeCaptureSession)
            .filter(
                KnowledgeCaptureSession.id == capture_uuid,
                KnowledgeCaptureSession.tenant_id == tenant_uuid,
            )
            .first()
        )
        if capture is None:
            raise RuntimeError("knowledge capture not found")
        if capture.status == "ready_for_review":
            return {
                "session_id": session_id,
                "status": capture.status,
                "idempotent": True,
            }
        if capture.status not in {"queued", "transcribing"}:
            raise RuntimeError(f"knowledge capture is {capture.status}")
        if not settings.VOICE_STT_ENABLED:
            raise RuntimeError("VOICE_STT_ENABLED is false")

        owner = db.query(User).filter(User.id == capture.owner_id).first()
        if owner is None:
            raise RuntimeError("knowledge capture owner not found")
        chunks = (
            db.query(KnowledgeCaptureChunk)
            .filter(
                KnowledgeCaptureChunk.tenant_id == tenant_uuid,
                KnowledgeCaptureChunk.session_id == capture_uuid,
                KnowledgeCaptureChunk.deleted_at.is_(None),
            )
            .order_by(KnowledgeCaptureChunk.sequence.asc())
            .all()
        )
        if not chunks or len(chunks) != int(capture.expected_chunks or 0):
            raise RuntimeError("knowledge capture has missing chunks")

        # Compatibility for captures queued before Phase B deployment. New
        # sessions already have this revision from the complete endpoint.
        if not capture.source_asset_revision_id:
            from app.services.asset_projection import finalize_capture_asset_revision

            finalize_capture_asset_revision(db, capture=capture, chunks=chunks)

        from app.services.ingestion_orchestrator import get_ingestion_orchestrator

        orchestrator = get_ingestion_orchestrator()
        ingestion_job = orchestrator.ensure_job(
            db,
            tenant_id=tenant_uuid,
            asset_revision_id=capture.source_asset_revision_id,
            capabilities=("transcribe", "timestamp", "terminology_correction"),
            idempotency_key=f"capture:{capture_uuid}:transcript",
            correlation_id=str(capture_uuid),
        )
        ingestion_job_id = ingestion_job.id
        if ingestion_job.status in {"queued", "failed"}:
            orchestrator.transition(
                db,
                ingestion_job,
                to_status="running",
                phase="transcribing",
            )

        capture.status = "transcribing"
        capture.error = {}
        db.commit()

        storage = get_storage_backend()
        dictionary = get_term_dictionary_service(db)
        db.query(KnowledgeCaptureTranscriptSegment).filter(
            KnowledgeCaptureTranscriptSegment.session_id == capture_uuid
        ).delete(synchronize_session=False)

        transcript_parts: list[str] = []
        total_seconds = 0.0
        for chunk in chunks:
            audio_data = storage.get_bytes(chunk.storage_key)
            result = transcribe_long_interview_chunk(
                audio_data,
                filename=f"interview.{chunk.mime_type.rsplit('/', 1)[-1].replace('mpeg', 'mp3').replace('mp4', 'm4a')}",
                content_type=chunk.mime_type,
            )
            raw_text = (result.text or "").strip()
            corrected_text = (
                dictionary.correct_transcript(tenant_uuid, raw_text) if raw_text else ""
            )
            text = corrected_text or raw_text
            if text:
                transcript_parts.append(text)
            segment_rows = result.segments or [
                {"start": 0, "end": chunk.duration_ms / 1000, "text": raw_text}
            ]
            for segment in segment_rows:
                segment_text = str(segment.get("text") or "").strip()
                if not segment_text:
                    continue
                start_ms = int(
                    chunk.offset_ms + float(segment.get("start") or 0) * 1000
                )
                end_ms = int(chunk.offset_ms + float(segment.get("end") or 0) * 1000)
                db.add(
                    KnowledgeCaptureTranscriptSegment(
                        tenant_id=tenant_uuid,
                        session_id=capture_uuid,
                        chunk_id=chunk.id,
                        sequence=chunk.sequence,
                        # Generic STT does not identify speakers.  Do not invent a
                        # speaker label; diarization will be enabled only when its
                        # specialized model is configured and evaluated.
                        speaker=(
                            str(segment.get("speaker"))
                            if segment.get("speaker")
                            else None
                        ),
                        start_ms=start_ms,
                        end_ms=max(start_ms, end_ms),
                        raw_text=segment_text,
                        corrected_text=(
                            dictionary.correct_transcript(tenant_uuid, segment_text)
                            or None
                        ),
                    )
                )
            chunk.transcription_state = "completed"
            total_seconds += float(result.duration_seconds or chunk.duration_ms / 1000)

        save_transcript = bool(
            (capture.transcript_policy_snapshot or {}).get("save_transcript", True)
        )
        capture.transcript = "\n\n".join(transcript_parts) if save_transcript else None
        capture.transcript_metadata = {
            **dict(capture.transcript_metadata or {}),
            "provider": settings.VOICE_STT_PROVIDER,
            "model": settings.LONG_INTERVIEW_STT_MODEL,
            "segment_count": db.query(KnowledgeCaptureTranscriptSegment)
            .filter(KnowledgeCaptureTranscriptSegment.session_id == capture_uuid)
            .count(),
            "transcript_redacted": not save_transcript,
            "speaker_diarization": True,
            "speaker_identity_scope": "chunk",
        }
        from app.services.asset_projection import project_capture_transcript_segments

        transcript_segments = (
            db.query(KnowledgeCaptureTranscriptSegment)
            .filter(
                KnowledgeCaptureTranscriptSegment.tenant_id == tenant_uuid,
                KnowledgeCaptureTranscriptSegment.session_id == capture_uuid,
            )
            .order_by(
                KnowledgeCaptureTranscriptSegment.start_ms.asc(),
                KnowledgeCaptureTranscriptSegment.sequence.asc(),
            )
            .all()
        )
        project_capture_transcript_segments(
            db,
            capture=capture,
            segments=transcript_segments,
            provider=settings.VOICE_STT_PROVIDER,
            provider_version=settings.LONG_INTERVIEW_STT_MODEL,
        )
        capture.status = "ready_for_review"
        if ingestion_job.status == "running":
            orchestrator.transition(
                db,
                ingestion_job,
                to_status="review_required",
                phase="human_review",
                quality_state="review_required",
                readiness={
                    "transcript": True,
                    "timestamped_evidence": True,
                    "active_knowledge": False,
                },
            )
        record_cost_db(
            db,
            tenant_id=tenant_uuid,
            task_type="knowledge_capture_stt",
            task_id=str(capture_uuid),
            stt_cost=total_seconds * settings.VOICE_STT_COST_PER_SECOND,
            details={
                "provider": settings.VOICE_STT_PROVIDER,
                "model": settings.LONG_INTERVIEW_STT_MODEL,
                "duration_seconds": total_seconds,
                "chunk_count": len(chunks),
            },
        )
        db.commit()

        # Audio is required while processing even when the tenant elected not to
        # retain originals.  Delete only after a successful transcription commit.
        if not bool((capture.audio_policy_snapshot or {}).get("save_audio", False)):
            for chunk in chunks:
                storage.delete(chunk.storage_key)
                chunk.deleted_at = datetime.now(timezone.utc)
            from app.services.asset_projection import mark_capture_audio_purged

            mark_capture_audio_purged(db, capture=capture)
            db.commit()
        return {
            "session_id": session_id,
            "status": "ready_for_review",
            "chunks": len(chunks),
        }
    except Exception as exc:
        db.rollback()
        logger.exception("transcribe_knowledge_capture failed: session=%s", session_id)
        exhausted = getattr(self.request, "retries", 0) >= self.max_retries
        try:
            from app.models.ingestion import IngestionJob
            from app.models.mka import KnowledgeCaptureSession
            from app.services.ingestion_orchestrator import (
                get_ingestion_orchestrator,
            )
            from app.services.rls import apply_rls_context

            tenant_uuid = UUID(tenant_id)
            apply_rls_context(db, tenant_uuid)
            capture = (
                db.query(KnowledgeCaptureSession)
                .filter(
                    KnowledgeCaptureSession.id == UUID(session_id),
                    KnowledgeCaptureSession.tenant_id == tenant_uuid,
                )
                .first()
            )
            if capture is not None:
                capture.status = "failed" if exhausted else "queued"
                capture.error = {
                    "code": "transcription_failed",
                    "message": "Transcription could not be completed",
                    "retryable": not exhausted,
                }
            if ingestion_job_id is not None:
                failed_job = (
                    db.query(IngestionJob)
                    .filter(
                        IngestionJob.tenant_id == tenant_uuid,
                        IngestionJob.id == ingestion_job_id,
                    )
                    .first()
                )
                if failed_job is not None and failed_job.status == "running":
                    get_ingestion_orchestrator().fail(
                        db,
                        failed_job,
                        code="transcription_failed",
                        message="Transcription could not be completed",
                        phase="transcribing",
                    )
            db.commit()
        except Exception:
            db.rollback()
        if exhausted:
            raise
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()
