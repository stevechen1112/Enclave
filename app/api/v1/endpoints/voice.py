"""
P1-1：Voice endpoint — 語音輸入入口。

POST /api/v1/voice/transcribe — 語音轉文字
POST /api/v1/voice/synthesize — 文字轉語音
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from app.api import deps
from app.models.user import User

router = APIRouter()


class SynthesizeRequest(BaseModel):
    text: str
    voice: str = ""


@router.post("/voice/transcribe")
async def transcribe_voice(
    file: UploadFile = File(...),
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

    return {
        "text": result.text,
        "is_draft": result.is_draft,
        "language": result.language,
        "confidence": result.confidence,
        "duration_seconds": result.duration_seconds,
        "segments": result.segments,
    }


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