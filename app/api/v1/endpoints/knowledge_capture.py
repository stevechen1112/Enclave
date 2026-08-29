"""Resumable long-form audio capture for knowledge interviews.

This intentionally does not reuse ``/voice/transcribe``: that endpoint is a
bounded, synchronous command input while an interview must survive weak mobile
networks and be processed after recording has finished.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api import deps
from app.api.deps_permissions import check_document_permission
from app.models.mka import (
    KnowledgeCaptureChunk,
    KnowledgeCaptureSession,
    KnowledgeCaptureTranscriptSegment,
)
from app.models.user import User
from app.services.audio_retention import get_policy_db, set_policy_db
from app.services.intake_context import IntakeContextError, parse_intake_context
from app.services.storage import build_storage_key, get_storage_backend
from app.services.term_dictionary import get_term_dictionary_service

router = APIRouter()

_DATA_CLASSIFICATIONS = {"public", "internal", "confidential", "restricted"}

_ALLOWED_MIME_TYPES = {
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
}


class CreateCaptureBody(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    equipment_id: str | None = Field(default=None, max_length=120)
    interviewee: str | None = Field(default=None, max_length=120)
    interviewer: str | None = Field(default=None, max_length=120)
    consent: bool = False
    consent_version: str = Field(default="core-capture-v1", min_length=1, max_length=80)
    source_module: str = Field(default="core", min_length=1, max_length=80)
    purpose: str = Field(default="knowledge_capture", min_length=1, max_length=120)
    department_id: UUID | None = None
    data_classification: str = Field(default="confidential", max_length=32)
    context_metadata: dict[str, Any] = Field(default_factory=dict)


class CompleteCaptureBody(BaseModel):
    final_sequence: int = Field(ge=0, le=239)
    total_duration_ms: int = Field(ge=1, le=60 * 60 * 1000)


class UpdateCapturePolicyBody(BaseModel):
    save_audio: bool | None = None
    save_transcript: bool | None = None
    audio_retention_days: int | None = Field(default=None, ge=1, le=3650)
    transcript_retention_days: int | None = Field(default=None, ge=1, le=3650)
    encrypt_at_rest: bool | None = None
    audit_downloads: bool | None = None
    capture_max_duration_seconds: int | None = Field(
        default=None, ge=60, le=24 * 60 * 60
    )


class CorrectSegmentBody(BaseModel):
    corrected_text: str = Field(min_length=1, max_length=10000)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _session_or_404(db: Session, current_user: User, session_id: UUID) -> KnowledgeCaptureSession:
    row = (
        db.query(KnowledgeCaptureSession)
        .filter(
            KnowledgeCaptureSession.id == session_id,
            KnowledgeCaptureSession.tenant_id == current_user.tenant_id,
            KnowledgeCaptureSession.owner_id == current_user.id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="knowledge capture not found")
    return row


def _session_to_dict(row: KnowledgeCaptureSession, *, include_transcript: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": str(row.id),
        "title": row.title,
        "equipment_id": row.equipment_id,
        "interviewee": row.interviewee,
        "interviewer": row.interviewer,
        "status": row.status,
        "received_chunks": row.received_chunks or 0,
        "expected_chunks": row.expected_chunks,
        "total_duration_ms": row.total_duration_ms or 0,
        "error": row.error or {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "source_asset_id": str(row.source_asset_id) if row.source_asset_id else None,
        "capture_metadata": dict(row.transcript_metadata or {}).get("capture", {}),
        "policy": {
            **dict(row.audio_policy_snapshot or {}),
            **dict(row.transcript_policy_snapshot or {}),
        },
    }
    if include_transcript:
        data["transcript"] = row.transcript
        data["transcript_metadata"] = row.transcript_metadata or {}
    return data


def _terminology_snapshot(db: Session, tenant_id: UUID) -> dict[str, Any]:
    terms = get_term_dictionary_service(db).list_terms(tenant_id)
    normalized = sorted(
        {
            str(item.get("term") or "").strip()
            for item in terms
            if str(item.get("term") or "").strip()
        }
    )
    encoded = json.dumps(normalized, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return {
        "terminology_count": len(normalized),
        "terminology_sha256": hashlib.sha256(encoded).hexdigest(),
    }


@router.get("/policy")
def get_capture_policy(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> dict[str, Any]:
    from app.config import settings

    check_document_permission(current_user, "create")
    retention = get_policy_db(db, current_user.tenant_id)
    return {
        "consent_version": "core-capture-v1",
        "max_duration_seconds": min(
            retention.capture_max_duration_seconds,
            settings.LONG_INTERVIEW_MAX_SECONDS,
        ),
        "chunk_max_seconds": settings.LONG_INTERVIEW_CHUNK_MAX_SECONDS,
        "chunk_max_bytes": settings.LONG_INTERVIEW_CHUNK_MAX_BYTES,
        "max_chunks": settings.LONG_INTERVIEW_MAX_CHUNKS,
        "audio_retention_days": retention.audio_retention_days,
        "transcript_retention_days": retention.transcript_retention_days,
        "save_audio": retention.save_audio,
        "save_transcript": retention.save_transcript,
        "encrypt_at_rest": retention.encrypt_at_rest,
        **_terminology_snapshot(db, current_user.tenant_id),
        "default_metadata": {
            "data_classification": "confidential",
            "source_module": "core",
            "purpose": "knowledge_capture",
        },
        "device_limitations": [
            "lock_screen_or_app_switch_may_interrupt_browser_capture",
            "keep_page_open_until_the_current_chunk_is_saved",
            "available_storage_is_controlled_by_the_browser_and_device",
        ],
    }


@router.put("/policy")
def update_capture_policy(
    body: UpdateCapturePolicyBody,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> dict[str, Any]:
    if not (
        current_user.is_superuser or current_user.role in {"owner", "admin"}
    ):
        raise HTTPException(status_code=403, detail="capture policy requires admin")
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status_code=400, detail="no fields to update")
    set_policy_db(db, current_user.tenant_id, **fields)
    db.commit()
    return get_capture_policy(db=db, current_user=current_user)


@router.post("")
def create_capture(
    body: CreateCaptureBody,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> dict[str, Any]:
    from app.config import settings
    from app.models.permission import Department

    check_document_permission(current_user, "create")
    if not body.consent:
        raise HTTPException(status_code=400, detail="consent is required before recording")
    if body.data_classification not in _DATA_CLASSIFICATIONS:
        raise HTTPException(status_code=400, detail="unsupported data classification")
    if body.department_id is not None:
        department = (
            db.query(Department.id)
            .filter(
                Department.tenant_id == current_user.tenant_id,
                Department.id == body.department_id,
                Department.is_active.is_(True),
            )
            .first()
        )
        if department is None:
            raise HTTPException(status_code=400, detail="department is not active in this tenant")
    try:
        context = parse_intake_context(
            json.dumps(body.context_metadata, ensure_ascii=False)
            if body.context_metadata
            else None
        )
    except IntakeContextError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    policy = get_policy_db(db, current_user.tenant_id)
    terminology = _terminology_snapshot(db, current_user.tenant_id)
    max_duration_seconds = min(
        policy.capture_max_duration_seconds,
        settings.LONG_INTERVIEW_MAX_SECONDS,
    )
    now = _utcnow()
    row = KnowledgeCaptureSession(
        tenant_id=current_user.tenant_id,
        owner_id=current_user.id,
        title=body.title.strip(),
        equipment_id=(body.equipment_id or "").strip() or None,
        interviewee=(body.interviewee or "").strip() or None,
        interviewer=(body.interviewer or "").strip() or None,
        consent_version=body.consent_version,
        consented_at=now,
        audio_policy_snapshot={
            "save_audio": policy.save_audio,
            "audio_retention_days": policy.audio_retention_days,
            "encrypt_at_rest": policy.encrypt_at_rest,
            "max_duration_seconds": max_duration_seconds,
            "chunk_max_seconds": settings.LONG_INTERVIEW_CHUNK_MAX_SECONDS,
        },
        transcript_policy_snapshot={
            "save_transcript": policy.save_transcript,
            "transcript_retention_days": policy.transcript_retention_days,
            **terminology,
        },
        transcript_metadata={
            "capture": {
                "source_module": body.source_module.strip(),
                "purpose": body.purpose.strip(),
                "department_id": str(body.department_id) if body.department_id else None,
                "data_classification": body.data_classification,
                "context_metadata": context,
            }
        },
        audio_expires_at=now + timedelta(days=policy.audio_retention_days),
        transcript_expires_at=now + timedelta(days=policy.transcript_retention_days),
    )
    db.add(row)
    db.flush()
    from app.services.asset_projection import ensure_capture_asset

    ensure_capture_asset(db, row)
    db.commit()
    db.refresh(row)
    return _session_to_dict(row)


@router.post("/{session_id}/chunks")
async def upload_chunk(
    session_id: UUID,
    file: UploadFile = File(...),
    sequence: int = Form(..., ge=0, le=239),
    offset_ms: int = Form(..., ge=0, le=60 * 60 * 1000),
    duration_ms: int = Form(..., ge=1, le=90 * 1000),
    sha256: str = Form(..., min_length=64, max_length=64),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> dict[str, Any]:
    check_document_permission(current_user, "create")
    from app.api.ingestion_guard import enforce_ingestion_queue_capacity
    from app.config import settings

    enforce_ingestion_queue_capacity()

    row = _session_or_404(db, current_user, session_id)
    if row.status not in {"recording", "uploading"}:
        raise HTTPException(status_code=409, detail=f"capture is {row.status}")
    if duration_ms > settings.LONG_INTERVIEW_CHUNK_MAX_SECONDS * 1000:
        raise HTTPException(status_code=400, detail="audio chunk duration exceeds limit")
    session_max_seconds = min(
        int(
            (row.audio_policy_snapshot or {}).get("max_duration_seconds")
            or settings.LONG_INTERVIEW_MAX_SECONDS
        ),
        settings.LONG_INTERVIEW_MAX_SECONDS,
    )
    if offset_ms + duration_ms > session_max_seconds * 1000:
        raise HTTPException(status_code=400, detail="interview duration exceeds limit")

    mime_type = (file.content_type or "").split(";", 1)[0].strip().lower()
    extension = _ALLOWED_MIME_TYPES.get(mime_type)
    if extension is None:
        raise HTTPException(status_code=415, detail="unsupported interview audio format")
    try:
        supplied_hash = bytes.fromhex(sha256)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="sha256 must be hexadecimal") from exc
    if len(supplied_hash) != 32:
        raise HTTPException(status_code=400, detail="sha256 must be 32 bytes")

    tmp_path = ""
    received = 0
    digest = hashlib.sha256()
    try:
        with tempfile.NamedTemporaryFile(prefix="enclave-capture-", suffix=f".{extension}", delete=False) as tmp:
            tmp_path = tmp.name
            while True:
                block = await file.read(1024 * 1024)
                if not block:
                    break
                received += len(block)
                if received > settings.LONG_INTERVIEW_CHUNK_MAX_BYTES:
                    raise HTTPException(status_code=413, detail="audio chunk exceeds limit")
                digest.update(block)
                tmp.write(block)
    except Exception:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
    finally:
        await file.close()

    if received == 0:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise HTTPException(status_code=400, detail="empty audio chunk")
    actual_hash = digest.hexdigest()
    if actual_hash != sha256.lower():
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise HTTPException(status_code=400, detail="audio chunk checksum mismatch")

    existing = (
        db.query(KnowledgeCaptureChunk)
        .filter(
            KnowledgeCaptureChunk.tenant_id == current_user.tenant_id,
            KnowledgeCaptureChunk.session_id == session_id,
            KnowledgeCaptureChunk.sequence == sequence,
        )
        .first()
    )
    if existing is not None:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        if existing.sha256 != actual_hash:
            raise HTTPException(status_code=409, detail="chunk sequence already exists with different content")
        return {
            "id": str(existing.id),
            "sequence": existing.sequence,
            "duplicate": True,
            "received_chunks": row.received_chunks or 0,
        }

    from app.services.cost_guardrails import reserve_media_cost

    cost_reservation = reserve_media_cost(
        db,
        tenant_id=current_user.tenant_id,
        media_kind="audio",
        duration_ms=duration_ms,
        task_id=f"capture:{session_id}:{sequence}:{actual_hash}",
    )
    if not cost_reservation.get("allowed", False):
        db.rollback()
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
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

    chunk = KnowledgeCaptureChunk(
        tenant_id=current_user.tenant_id,
        session_id=session_id,
        sequence=sequence,
        offset_ms=offset_ms,
        duration_ms=duration_ms,
        storage_key="pending",
        mime_type=mime_type,
        size_bytes=received,
        sha256=actual_hash,
    )
    db.add(chunk)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)
        concurrent = (
            db.query(KnowledgeCaptureChunk)
            .filter(
                KnowledgeCaptureChunk.tenant_id == current_user.tenant_id,
                KnowledgeCaptureChunk.session_id == session_id,
                KnowledgeCaptureChunk.sequence == sequence,
            )
            .first()
        )
        if concurrent is not None and concurrent.sha256 == actual_hash:
            capture = _session_or_404(db, current_user, session_id)
            return {
                "id": str(concurrent.id),
                "sequence": concurrent.sequence,
                "duplicate": True,
                "received_chunks": capture.received_chunks or 0,
            }
        raise HTTPException(status_code=409, detail="chunk sequence upload conflict")
    storage_key = build_storage_key(current_user.tenant_id, chunk.id, extension)
    try:
        get_storage_backend().put(storage_key, tmp_path)
        tmp_path = ""  # StorageBackend consumed the temporary source file.
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail="unable to persist audio chunk") from exc
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

    chunk.storage_key = storage_key
    row.received_chunks = int(row.received_chunks or 0) + 1
    row.total_duration_ms = max(int(row.total_duration_ms or 0), offset_ms + duration_ms)
    row.status = "uploading"
    try:
        db.commit()
    except Exception:
        db.rollback()
        try:
            get_storage_backend().delete(storage_key)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail="unable to commit audio chunk")
    return {
        "id": str(chunk.id),
        "sequence": chunk.sequence,
        "duplicate": False,
        "received_chunks": row.received_chunks,
    }


@router.post("/{session_id}/complete")
def complete_capture(
    session_id: UUID,
    body: CompleteCaptureBody,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> dict[str, Any]:
    from app.config import settings

    check_document_permission(current_user, "create")
    row = _session_or_404(db, current_user, session_id)
    if row.status in {"queued", "transcribing", "ready_for_review"}:
        return {**_session_to_dict(row), "queue_enqueued": True, "idempotent": True}
    if row.status not in {"recording", "uploading"}:
        raise HTTPException(status_code=409, detail=f"capture is {row.status}")
    chunks = (
        db.query(KnowledgeCaptureChunk)
        .filter(
            KnowledgeCaptureChunk.tenant_id == current_user.tenant_id,
            KnowledgeCaptureChunk.session_id == session_id,
        )
        .order_by(KnowledgeCaptureChunk.sequence.asc())
        .all()
    )
    expected = list(range(body.final_sequence + 1))
    if [chunk.sequence for chunk in chunks] != expected:
        raise HTTPException(status_code=409, detail="some audio chunks have not been uploaded")
    if len(chunks) > settings.LONG_INTERVIEW_MAX_CHUNKS:
        raise HTTPException(status_code=400, detail="too many audio chunks")
    session_max_seconds = min(
        int(
            (row.audio_policy_snapshot or {}).get("max_duration_seconds")
            or settings.LONG_INTERVIEW_MAX_SECONDS
        ),
        settings.LONG_INTERVIEW_MAX_SECONDS,
    )
    if body.total_duration_ms > session_max_seconds * 1000:
        raise HTTPException(status_code=400, detail="interview duration exceeds limit")

    recorded_duration = sum(int(chunk.duration_ms or 0) for chunk in chunks)
    # The browser's clock is advisory; reject wildly inconsistent final metadata.
    if abs(recorded_duration - body.total_duration_ms) > max(15_000, recorded_duration // 5):
        raise HTTPException(status_code=400, detail="recording duration does not match uploaded chunks")

    row.expected_chunks = len(chunks)
    row.received_chunks = len(chunks)
    row.total_duration_ms = recorded_duration
    row.completed_at = _utcnow()
    row.status = "queued"
    from app.services.asset_projection import finalize_capture_asset_revision

    finalize_capture_asset_revision(db, capture=row, chunks=chunks)
    db.commit()

    queue_enqueued = True
    try:
        from app.tasks.mka_tasks import transcribe_knowledge_capture

        transcribe_knowledge_capture.delay(str(current_user.tenant_id), str(session_id))
    except Exception:
        # The durable queue state permits support staff or a later retry request to
        # resume processing; never pretend recording was lost when Celery is down.
        queue_enqueued = False

    return {**_session_to_dict(row), "queue_enqueued": queue_enqueued}


@router.post("/{session_id}/retry")
def retry_capture(
    session_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> dict[str, Any]:
    check_document_permission(current_user, "create")
    row = _session_or_404(db, current_user, session_id)
    if row.status not in {"queued", "failed"}:
        raise HTTPException(status_code=409, detail=f"capture cannot be retried from {row.status}")
    row.status = "queued"
    row.error = {}
    db.commit()
    try:
        from app.tasks.mka_tasks import transcribe_knowledge_capture

        transcribe_knowledge_capture.delay(str(current_user.tenant_id), str(session_id))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="transcription queue unavailable") from exc
    return _session_to_dict(row)


@router.get("/{session_id}")
def get_capture(
    session_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> dict[str, Any]:
    check_document_permission(current_user, "create")
    row = _session_or_404(db, current_user, session_id)
    return _session_to_dict(row, include_transcript=True)


@router.get("/{session_id}/transcript")
def get_capture_transcript(
    session_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> dict[str, Any]:
    check_document_permission(current_user, "create")
    row = _session_or_404(db, current_user, session_id)
    segments = (
        db.query(KnowledgeCaptureTranscriptSegment)
        .filter(
            KnowledgeCaptureTranscriptSegment.tenant_id == current_user.tenant_id,
            KnowledgeCaptureTranscriptSegment.session_id == session_id,
        )
        .order_by(
            KnowledgeCaptureTranscriptSegment.sequence.asc(),
            KnowledgeCaptureTranscriptSegment.start_ms.asc(),
        )
        .all()
    )
    return {
        "session_id": str(row.id),
        "status": row.status,
        "transcript": row.transcript,
        "segments": [
            {
                "id": str(segment.id),
                "speaker": segment.speaker,
                "start_ms": segment.start_ms,
                "end_ms": segment.end_ms,
                "text": segment.corrected_text or segment.raw_text,
                "raw_text": segment.raw_text,
            }
            for segment in segments
        ],
    }


@router.patch("/{session_id}/transcript/segments/{segment_id}")
def correct_capture_transcript_segment(
    session_id: UUID,
    segment_id: UUID,
    body: CorrectSegmentBody,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> dict[str, Any]:
    check_document_permission(current_user, "create")
    row = _session_or_404(db, current_user, session_id)
    if row.status != "ready_for_review":
        raise HTTPException(status_code=409, detail="transcript is not ready for correction")
    segment = (
        db.query(KnowledgeCaptureTranscriptSegment)
        .filter(
            KnowledgeCaptureTranscriptSegment.id == segment_id,
            KnowledgeCaptureTranscriptSegment.tenant_id == current_user.tenant_id,
            KnowledgeCaptureTranscriptSegment.session_id == session_id,
        )
        .first()
    )
    if segment is None:
        raise HTTPException(status_code=404, detail="transcript segment not found")
    segment.corrected_text = body.corrected_text.strip()
    segment.corrected_by = current_user.id
    segment.corrected_at = _utcnow()
    segments = (
        db.query(KnowledgeCaptureTranscriptSegment)
        .filter(KnowledgeCaptureTranscriptSegment.session_id == session_id)
        .order_by(KnowledgeCaptureTranscriptSegment.sequence, KnowledgeCaptureTranscriptSegment.start_ms)
        .all()
    )
    row.transcript = "\n\n".join((item.corrected_text or item.raw_text).strip() for item in segments if (item.corrected_text or item.raw_text).strip())
    db.commit()
    return {"id": str(segment.id), "text": segment.corrected_text}
