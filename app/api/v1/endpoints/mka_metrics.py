"""MKA metrics / events dashboard API."""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api import deps
from app.models.mka import MKAEvent
from app.models.user import User

router = APIRouter()


class EventCreate(BaseModel):
    event_type: str
    module_key: Optional[str] = None
    object_type: Optional[str] = None
    object_id: Optional[str] = None
    metrics: Dict[str, Any] = Field(default_factory=dict)


def record_mka_event(
    db: Session,
    *,
    tenant_id: UUID,
    user_id: Optional[UUID],
    event_type: str,
    module_key: Optional[str] = None,
    object_type: Optional[str] = None,
    object_id: Optional[str] = None,
    metrics: Optional[Dict[str, Any]] = None,
) -> MKAEvent:
    row = MKAEvent(
        tenant_id=tenant_id,
        user_id=user_id,
        event_type=event_type,
        module_key=module_key,
        object_type=object_type,
        object_id=object_id,
        metrics=metrics or {},
    )
    db.add(row)
    db.flush()
    return row


@router.post("/mka/events")
def create_event(
    body: EventCreate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
) -> Dict[str, Any]:
    row = record_mka_event(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        event_type=body.event_type,
        module_key=body.module_key,
        object_type=body.object_type,
        object_id=body.object_id,
        metrics=body.metrics,
    )
    db.commit()
    return {"id": str(row.id), "event_type": row.event_type}


@router.get("/mka/metrics/summary")
def metrics_summary(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
) -> Dict[str, Any]:
    """語音比例、任務完成、補問、模組使用、未審草稿等聚合。"""
    tenant_id = current_user.tenant_id
    rows = (
        db.query(MKAEvent.event_type, func.count(MKAEvent.id))
        .filter(MKAEvent.tenant_id == tenant_id)
        .group_by(MKAEvent.event_type)
        .all()
    )
    by_type = {k: int(v) for k, v in rows}
    module_rows = (
        db.query(MKAEvent.module_key, func.count(MKAEvent.id))
        .filter(MKAEvent.tenant_id == tenant_id, MKAEvent.module_key.isnot(None))
        .group_by(MKAEvent.module_key)
        .all()
    )
    by_module = {k: int(v) for k, v in module_rows if k}

    voice = by_type.get("voice_used", 0)
    typed = by_type.get("typed_used", 0)
    voice_ratio = (voice / (voice + typed)) if (voice + typed) else None

    # form draft backlog
    from app.models.mka import FormInstance
    draft_count = (
        db.query(func.count(FormInstance.id))
        .filter(
            FormInstance.tenant_id == tenant_id,
            FormInstance.status == "draft",
        )
        .scalar()
        or 0
    )
    pending_count = (
        db.query(func.count(FormInstance.id))
        .filter(
            FormInstance.tenant_id == tenant_id,
            FormInstance.status.in_(["pending_review", "pending_approval"]),
        )
        .scalar()
        or 0
    )

    return {
        "voice_ratio": voice_ratio,
        "task_completions": by_type.get("task_completed", 0),
        "followup_questions": by_type.get("followup_question", 0),
        "field_corrections": by_type.get("field_corrected", 0),
        "first_pass_completions": by_type.get("first_pass_complete", 0),
        "quote_started": by_type.get("quote_started", 0),
        "quote_completed": by_type.get("quote_completed", 0),
        "incident_started": by_type.get("incident_started", 0),
        "incident_completed": by_type.get("incident_completed", 0),
        "module_usage": by_module,
        "draft_forms": int(draft_count),
        "pending_review_forms": int(pending_count),
        "conflict_resolutions": by_type.get("sop_conflict_resolved", 0),
        "event_counts": by_type,
    }
