"""Know-how interview mode: consent → STT → segment → extract → draft card."""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api import deps
from app.api.deps_permissions import require_knowhow_author
from app.models.mka import KnowledgeCaptureSession, KnowhowCardModel
from app.models.user import User
from app.services.knowhow_lifecycle import get_knowhow_lifecycle_manager

router = APIRouter()


class ExtractBody(BaseModel):
    transcript: str = ""
    title: Optional[str] = None
    equipment_id: Optional[str] = None
    consent: bool = False
    audio_uri: Optional[str] = None
    session_id: Optional[UUID] = None


def _segment_topics(text: str) -> List[Dict[str, str]]:
    chunks = [c.strip() for c in text.replace("\r", "").split("\n\n") if c.strip()]
    if len(chunks) <= 1:
        chunks = [c.strip() for c in text.split("\n") if c.strip()]
    return [{"index": str(i + 1), "text": chunk[:2000]} for i, chunk in enumerate(chunks[:40])]


def _extract_structure(text: str) -> Dict[str, Any]:
    steps: List[str] = []
    conditions: List[str] = []
    risks: List[str] = []
    exceptions: List[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if any(k in s for k in ("步驟", "先", "然後", "接著", "最後")) or (s[:1].isdigit()):
            steps.append(s)
        elif any(k in s for k in ("若", "如果", "當", "條件")):
            conditions.append(s)
        elif any(k in s for k in ("風險", "注意", "危險", "禁止", "安全")):
            risks.append(s)
        elif any(k in s for k in ("例外", "除非", "特殊")):
            exceptions.append(s)
        elif len(steps) < 3:
            steps.append(s)
    return {
        "steps": steps[:50],
        "conditions": conditions[:30],
        "risks": risks[:30],
        "exceptions": exceptions[:30],
        "segments": _segment_topics(text),
    }


@router.post("/knowhow/interview/extract")
def extract_interview(
    body: ExtractBody,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_knowhow_author),
) -> Dict[str, Any]:
    if not body.consent:
        raise HTTPException(status_code=400, detail="consent required for interview capture")
    transcript = (body.transcript or "").strip()
    capture_audio_uri = body.audio_uri
    if not transcript and body.session_id:
        capture = (
            db.query(KnowledgeCaptureSession)
            .filter(
                KnowledgeCaptureSession.id == body.session_id,
                KnowledgeCaptureSession.tenant_id == current_user.tenant_id,
                KnowledgeCaptureSession.owner_id == current_user.id,
            )
            .first()
        )
        if capture is None:
            raise HTTPException(status_code=404, detail="knowledge capture session not found")
        if capture.status != "ready_for_review":
            raise HTTPException(status_code=409, detail="knowledge capture transcript is not ready")
        transcript = (capture.transcript or "").strip()
        if not capture_audio_uri:
            capture_audio_uri = f"capture://{capture.id}"
        if not body.title:
            body.title = capture.title
        if not body.equipment_id:
            body.equipment_id = capture.equipment_id
    if not transcript:
        raise HTTPException(status_code=400, detail="transcript required")

    extracted = _extract_structure(transcript)
    title = body.title or (extracted["steps"][0][:40] if extracted["steps"] else "訪談草稿")
    card = KnowhowCardModel(
        tenant_id=current_user.tenant_id,
        owner_id=current_user.id,
        card_id=f"kh-{uuid4().hex[:12]}",
        title=title,
        summary=transcript[:240],
        status="draft",
        steps=extracted["steps"],
        risks=extracted["risks"],
        cautions=extracted["conditions"] + extracted["exceptions"],
        equipment_ids=[body.equipment_id] if body.equipment_id else [],
        source_type="audio" if capture_audio_uri else "manual",
        source_audio_uri=capture_audio_uri,
        transcript_id=str(body.session_id) if body.session_id else None,
        interviewer=str(current_user.id),
    )
    db.add(card)
    db.flush()

    lifecycle = get_knowhow_lifecycle_manager(db=db, tenant_id=current_user.tenant_id)
    lifecycle.record_lineage(
        card_id=card.id,
        audio_uri=capture_audio_uri or "",
        transcript_id=str(body.session_id or ""),
        recorded_by=current_user.id,
        consent_obtained=True,
        consent_by=current_user.id,
    )
    db.commit()
    db.refresh(card)
    return {
        "card_id": str(card.id),
        "knowhow_card_id": card.card_id,
        "title": title,
        "status": "draft",
        "extracted": extracted,
        "message": "已建立知識卡草稿，請人工編輯後送審",
    }
