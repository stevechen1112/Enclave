"""Voice endpoints with persistent, tenant-scoped interaction sessions."""
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
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
):
    """語音轉文字（STT）。"""
    from app.config import settings
    if not settings.VOICE_STT_ENABLED:
        raise HTTPException(status_code=404, detail="Voice STT not enabled")

    from app.core.authorization import AuthorizationContext
    from app.services.voice_gateway import get_voice_gateway

    audio_data = await file.read()
    authz = AuthorizationContext.from_user(current_user)

    gateway = get_voice_gateway()
    result = gateway.transcribe(audio_data, authz)
    detected = gateway.extract_confirm_fields(
        result.text,
        [value.strip() for value in confirm_fields.split(",") if value.strip()],
    )
    metadata = {
        "provider": result.provider,
        "language": result.language,
        "segments": result.segments,
        "confidence": result.confidence,
        "duration_seconds": result.duration_seconds,
        "is_draft": result.is_draft,
        "filename": file.filename,
        "content_type": file.content_type,
    }
    try:
        row = MKARepository(db).save_transcript(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            text=result.text,
            metadata=metadata,
            detected_fields=detected,
            session_id=session_id,
            module_key=module_key,
            channel=channel,
            risk_level=risk_level,
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
            "detected_fields": detected,
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