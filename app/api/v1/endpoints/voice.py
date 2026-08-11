"""Voice endpoints with persistent, tenant-scoped interaction sessions."""
import json
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api import deps
from app.models.user import User
from app.services.mka_persistence import (
    MKAConflictError,
    MKANotFoundError,
    MKARepository,
    interaction_to_dict,
)

router = APIRouter()

_SCENE_FIELDS = {
    "site_id",
    "plant_id",
    "line_id",
    "equipment_id",
    "equipment_model",
    "work_order_id",
    "product_id",
    "part_number",
    "customer_id",
    "document_version_scope",
    "resolved_from",
    "resolved_at",
}


def _parse_scene_context(value: Optional[str]) -> Dict[str, str]:
    """Parse the client scene envelope without accepting arbitrary prompt data."""
    if not value:
        return {}
    try:
        payload = json.loads(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="invalid scene_context_json") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="scene_context_json must be an object")
    scene: Dict[str, str] = {}
    for key in _SCENE_FIELDS:
        raw = payload.get(key)
        if raw is None or raw == "":
            continue
        if not isinstance(raw, str) or len(raw) > 200:
            raise HTTPException(status_code=400, detail=f"invalid scene field: {key}")
        scene[key] = raw
    return scene


def _detected_field_values(items: list[Dict[str, Any]]) -> Dict[str, str]:
    """Stable frontend contract: field type -> latest detected value."""
    values: Dict[str, str] = {}
    for item in items:
        key = str(item.get("type") or "").strip()
        value = item.get("value")
        if key and value is not None:
            values[key] = str(value)
    return values


class SynthesizeRequest(BaseModel):
    text: str
    voice: str = ""


class TranscriptConfirmRequest(BaseModel):
    confirmed_text: Optional[str] = None
    confirmed_fields: Dict[str, Any] = Field(default_factory=dict)


def _raise_mka(exc: Exception) -> None:
    if isinstance(exc, MKANotFoundError):
        raise HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, MKAConflictError):
        raise HTTPException(status_code=409, detail=str(exc))
    raise HTTPException(status_code=400, detail=str(exc))


@router.post("/voice/transcribe")
async def transcribe_voice(
    file: UploadFile = File(...),
    session_id: Optional[UUID] = None,
    module_key: Optional[str] = None,
    channel: str = "web",
    risk_level: str = "low",
    confirm_fields: str = "amount,part_number,quantity,date,customer",
    scene_context_json: Optional[str] = None,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
):
    """語音轉文字（STT）。"""
    from app.config import settings
    if not settings.VOICE_STT_ENABLED:
        raise HTTPException(status_code=404, detail="Voice STT not enabled")

    from app.core.authorization import AuthorizationContext
    from app.services.voice_gateway import get_voice_gateway

    # 串流讀取並強制位元組上限，避免整檔無限制進記憶體（對齊 documents 上傳防線）
    max_bytes = settings.VOICE_MAX_AUDIO_BYTES
    upload_name = file.filename or "audio.webm"
    upload_ctype = file.content_type or "audio/webm"
    chunks: list[bytes] = []
    received = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        received += len(chunk)
        if received > max_bytes:
            await file.close()
            raise HTTPException(
                status_code=413,
                detail=(
                    f"音訊過大，上限 {max_bytes // (1024 * 1024)} MB"
                    f"（約 {settings.VOICE_MAX_AUDIO_SECONDS} 秒）"
                ),
            )
        chunks.append(chunk)
    await file.close()
    if received == 0:
        raise HTTPException(status_code=400, detail="音訊為空")
    audio_data = b"".join(chunks)
    authz = AuthorizationContext.from_user(current_user)

    gateway = get_voice_gateway()
    import time as _time

    from app.observability.business_metrics import record_mka_stt
    started = _time.monotonic()
    try:
        result = gateway.transcribe(
            audio_data,
            authz,
            filename=upload_name,
            content_type=upload_ctype,
        )
    except Exception:
        record_mka_stt(duration_seconds=_time.monotonic() - started, ok=False)
        raise HTTPException(status_code=502, detail="STT provider error")
    if result.duration_seconds > settings.VOICE_MAX_AUDIO_SECONDS:
        record_mka_stt(duration_seconds=_time.monotonic() - started, ok=False)
        raise HTTPException(
            status_code=400,
            detail=(
                f"音訊長度 {result.duration_seconds:.0f} 秒超過上限"
                f" {settings.VOICE_MAX_AUDIO_SECONDS} 秒"
            ),
        )
    record_mka_stt(duration_seconds=_time.monotonic() - started, ok=True)

    raw_text = result.text
    try:
        from app.services.term_dictionary import get_term_dictionary_service
        result.text = get_term_dictionary_service(db).correct_transcript(
            current_user.tenant_id, raw_text
        )
    except Exception:
        # A dictionary outage must not turn a successful STT call into data loss.
        result.text = raw_text

    detected_details = gateway.extract_confirm_fields(
        result.text,
        [value.strip() for value in confirm_fields.split(",") if value.strip()],
    )
    detected_values = _detected_field_values(detected_details)
    scene_context = _parse_scene_context(scene_context_json)
    # §12.1 租戶保留政策：save_transcript=false 時只存 metadata，不落地轉寫文字
    from app.services.audio_retention import get_policy_db, record_cost_db
    policy = get_policy_db(db, current_user.tenant_id)
    stored_text = result.text if policy.save_transcript else ""
    metadata = {
        "provider": result.provider,
        "language": result.language,
        "segments": result.segments,
        "confidence": result.confidence,
        "duration_seconds": result.duration_seconds,
        "is_draft": result.is_draft,
        "filename": file.filename,
        "content_type": file.content_type,
        "transcript_redacted": not policy.save_transcript,
        "original_text": raw_text if raw_text != result.text else None,
        "term_corrected": raw_text != result.text,
    }
    try:
        row = MKARepository(db).save_transcript(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            text=stored_text,
            metadata=metadata,
            detected_fields=detected_details,
            session_id=session_id,
            module_key=module_key,
            channel=channel,
            scene_context=scene_context,
            risk_level=risk_level,
        )
        # §13.4 COGS：每次 STT 完成記錄成本
        record_cost_db(
            db,
            tenant_id=current_user.tenant_id,
            task_type="stt",
            task_id=str(row.id),
            stt_cost=result.duration_seconds * settings.VOICE_STT_COST_PER_SECOND,
            details={
                "provider": result.provider,
                "duration_seconds": result.duration_seconds,
                "audio_bytes": received,
            },
        )
        db.commit()
        db.refresh(row)
        # Preserve every existing response field and add the persistence contract.
        return {
            "text": result.text,
            "is_draft": result.is_draft,
            "language": result.language,
            "confidence": result.confidence,
            "duration_seconds": result.duration_seconds,
            "segments": result.segments,
            "session_id": str(row.id),
            "detected_fields": detected_values,
            "detected_field_details": detected_details,
            "term_corrected": raw_text != result.text,
            "scene_context": scene_context,
            "needs_confirmation": True,
        }
    except Exception as exc:
        db.rollback()
        _raise_mka(exc)


@router.post("/voice/sessions/{session_id}/confirm")
def confirm_transcript(
    session_id: UUID,
    request: TranscriptConfirmRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
):
    try:
        row = MKARepository(db).confirm_transcript(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            session_id=session_id,
            confirmed_text=request.confirmed_text,
            confirmed_fields=request.confirmed_fields,
        )
        db.commit()
        db.refresh(row)
        return interaction_to_dict(row)
    except Exception as exc:
        db.rollback()
        _raise_mka(exc)


@router.post("/voice/sessions/{session_id}/resolve")
def resolve_voice_session(
    session_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
):
    """Complete a session; high-risk sessions fail closed until confirmation."""
    try:
        row = MKARepository(db).resolve_interaction(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            session_id=session_id,
        )
        db.commit()
        db.refresh(row)
        return interaction_to_dict(row)
    except Exception as exc:
        db.rollback()
        _raise_mka(exc)


@router.post("/voice/synthesize")
async def synthesize_voice(
    request: SynthesizeRequest,
    current_user: User = Depends(deps.get_current_verified_user),
):
    """文字轉語音（TTS）。"""
    from app.config import settings
    if not settings.VOICE_TTS_ENABLED:
        raise HTTPException(status_code=404, detail="Voice TTS not enabled")

    from app.core.authorization import AuthorizationContext
    from app.services.voice_gateway import get_voice_gateway

    authz = AuthorizationContext.from_user(current_user)
    gateway = get_voice_gateway()
    audio = gateway.synthesize(request.text, authz, voice=request.voice)

    from fastapi.responses import Response
    return Response(content=audio, media_type="audio/mpeg")