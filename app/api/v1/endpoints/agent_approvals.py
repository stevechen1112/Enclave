"""Phase 6 — Agent approval API (persistent)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api import deps
from app.api.deps_permissions import require_admin
from app.models.user import User
from app.models.agent_approval import AgentApprovalRequest

router = APIRouter(prefix="/agent-approvals", tags=["agent-approvals"])


class ApprovalAction(BaseModel):
    reason: str = ""


@router.get("/pending")
def list_pending(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_admin),
) -> List[Dict[str, Any]]:
    rows = (
        db.query(AgentApprovalRequest)
        .filter(
            AgentApprovalRequest.tenant_id == current_user.tenant_id,
            AgentApprovalRequest.status == "pending",
        )
        .order_by(AgentApprovalRequest.created_at.desc())
        .limit(50)
        .all()
    )
    return [
        {
            "id": str(r.id),
            "tool_name": r.tool_name,
            "tool_risk": r.tool_risk,
            "action_summary": r.action_summary,
            "actor_id": str(r.actor_id),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.post("/{request_id}/approve")
def approve_request(
    request_id: UUID,
    body: ApprovalAction,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    row = db.query(AgentApprovalRequest).filter(AgentApprovalRequest.id == request_id).first()
    if not row or row.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="審批請求不存在")
    row.status = "approved"
    row.approved_by = current_user.id
    row.approved_at = datetime.now(timezone.utc)
    row.reason = body.reason
    db.commit()
    return {"status": "approved", "request_id": str(request_id)}


@router.post("/{request_id}/reject")
def reject_request(
    request_id: UUID,
    body: ApprovalAction,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    row = db.query(AgentApprovalRequest).filter(AgentApprovalRequest.id == request_id).first()
    if not row or row.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="審批請求不存在")
    row.status = "rejected"
    row.approved_by = current_user.id
    row.approved_at = datetime.now(timezone.utc)
    row.reason = body.reason
    db.commit()
    return {"status": "rejected", "request_id": str(request_id)}
