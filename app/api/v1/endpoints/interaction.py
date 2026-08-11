"""
MKA Interaction API — §5.2。

POST /interaction/transcriptions — 音訊上傳 → STT → tentative transcript
POST /interaction/sessions — 建立 module/channel/scene session
PATCH /interaction/sessions/{id}/transcript — 人工修正與確認
POST /interaction/sessions/{id}/resolve — Module Router → chat/form/tool
"""
from __future__ import annotations

from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api import deps
from app.models.user import User

router = APIRouter()


class SessionCreateRequest(BaseModel):
    module_key: Optional[str] = None
    channel: str = "web"
    scene_context: Dict[str, Any] = Field(default_factory=dict)
    risk_level: str = "low"


class TranscriptPatchRequest(BaseModel):
    transcript: str
    confirmed: bool = False


class ResolveRequest(BaseModel):
    query: str = ""
    action: str = "chat"  # chat | form | tool


@router.post("/interaction/transcriptions")
async def create_transcription(
    file: UploadFile = File(...),
    current_user: User = Depends(deps.get_current_verified_user),
    db: Session = Depends(deps.get_db),
):
    """音訊上傳 → STT → tentative transcript（§5.2）。"""
    from app.config import settings
    if not settings.VOICE_STT_ENABLED:
        raise HTTPException(status_code=404, detail="Voice STT not enabled")

    from app.core.authorization import AuthorizationContext
    from app.services.voice_gateway import get_voice_gateway

    audio_data = await file.read()
    authz = AuthorizationContext.from_user(current_user)

    gateway = get_voice_gateway()
    result = gateway.transcribe(audio_data, authz)

    # 用專有詞字典修正轉寫（獨立於 knowhow card）
    corrected_text = result.text
    try:
        from app.services.term_dictionary import get_term_dictionary_service
        term_svc = get_term_dictionary_service(db)
        corrected_text = term_svc.correct_transcript(current_user.tenant_id, result.text)
    except Exception:
        pass  # term dictionary 不可用時不阻塞

    return {
        "text": corrected_text,
        "original_text": result.text,
        "is_draft": result.is_draft,
        "language": result.language,
        "confidence": result.confidence,
        "duration_seconds": result.duration_seconds,
        "segments": result.segments,
        "corrected": corrected_text != result.text,
    }


@router.post("/interaction/sessions")
def create_session(
    request: SessionCreateRequest,
    current_user: User = Depends(deps.get_current_verified_user),
    db: Session = Depends(deps.get_db),
):
    """建立 interaction session（§5.2）。"""
    from app.models.mka import InteractionSession

    session = InteractionSession(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        module_key=request.module_key,
        channel=request.channel,
        scene_context=request.scene_context,
        risk_level=request.risk_level,
        state="active",
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    return {
        "id": str(session.id),
        "module_key": session.module_key,
        "channel": session.channel,
        "state": session.state,
        "scene_context": session.scene_context,
    }


@router.patch("/interaction/sessions/{session_id}/transcript")
def patch_transcript(
    session_id: UUID,
    request: TranscriptPatchRequest,
    current_user: User = Depends(deps.get_current_verified_user),
    db: Session = Depends(deps.get_db),
):
    """人工修正與確認 transcript（§5.2）。"""
    from app.models.mka import InteractionSession
    from datetime import datetime, timezone

    session = (
        db.query(InteractionSession)
        .filter(
            InteractionSession.id == session_id,
            InteractionSession.tenant_id == current_user.tenant_id,
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    session.transcript = request.transcript
    if request.confirmed:
        session.transcript_confirmed_at = datetime.now(timezone.utc)
        session.state = "active"  # 確認後可進入 resolve

    db.commit()

    return {
        "id": str(session.id),
        "transcript": session.transcript,
        "confirmed": request.confirmed,
        "transcript_confirmed_at": session.transcript_confirmed_at.isoformat() if session.transcript_confirmed_at else None,
    }


@router.post("/interaction/sessions/{session_id}/resolve")
def resolve_session(
    session_id: UUID,
    request: ResolveRequest,
    current_user: User = Depends(deps.get_current_verified_user),
    db: Session = Depends(deps.get_db),
):
    """Module Router → chat/form/tool（§5.2）。

    transcript 未確認不得觸發高風險動作。
    """
    from app.models.mka import InteractionSession

    session = (
        db.query(InteractionSession)
        .filter(
            InteractionSession.id == session_id,
            InteractionSession.tenant_id == current_user.tenant_id,
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # 安全檢查：transcript 未確認不得觸發高風險動作
    if session.risk_level == "high" and not session.transcript_confirmed_at:
        raise HTTPException(
            status_code=403,
            detail="Transcript must be confirmed before high-risk actions",
        )

    # 根據 action 路由
    result: Dict[str, Any] = {
        "session_id": str(session.id),
        "action": request.action,
        "module_key": session.module_key,
    }

    if request.action == "chat":
        result["endpoint"] = "/api/v1/chat/stream"
        result["query"] = request.query or session.transcript or ""
    elif request.action == "form":
        result["endpoint"] = "/api/v1/forms/{form_name}/instances"
        result["query"] = request.query or session.transcript or ""
    elif request.action == "tool":
        result["endpoint"] = "/api/v1/mcp/tools/{tool_name}"
        result["query"] = request.query or session.transcript or ""
    else:
        raise HTTPException(status_code=400, detail=f"Unknown action: {request.action}")

    session.state = "completed"
    db.commit()

    return result