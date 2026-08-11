"""MKA Audio Retention Policy API — tenant-scoped audio retention settings.

§12.1 Audio retention:
  GET    /audio-policy
  PUT    /audio-policy
  GET    /audio-policy/costs
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api import deps
from app.api.deps_permissions import allow_all_authenticated, require_admin
from app.models.user import User
from app.services.audio_retention import (
    get_policy_db,
    set_policy_db,
    get_cost_summary_db,
)

router = APIRouter(prefix="/audio-policy", tags=["audio-policy"])


class AudioPolicyUpdateRequest(BaseModel):
    save_audio: Optional[bool] = None
    save_transcript: Optional[bool] = None
    audio_retention_days: Optional[int] = Field(None, ge=1, le=3650)
    transcript_retention_days: Optional[int] = Field(None, ge=1, le=3650)
    encrypt_at_rest: Optional[bool] = None
    audit_downloads: Optional[bool] = None


# ── Public endpoints ──

@router.get("")
def get_policy(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(allow_all_authenticated),
):
    """Get the current tenant's audio retention policy."""
    policy = get_policy_db(db, current_user.tenant_id)
    return policy.to_dict()


# ── Admin endpoints ──

@router.put("")
def update_policy(
    request: AudioPolicyUpdateRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_admin),
):
    """Update the tenant's audio retention policy (admin only)."""
    fields = {k: v for k, v in request.dict(exclude_none=True).items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="no fields to update")
    policy = set_policy_db(db, current_user.tenant_id, **fields)
    db.commit()
    return policy.to_dict()


@router.get("/costs")
def get_costs(
    task_type: Optional[str] = None,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_admin),
):
    """Get COGS cost summary for the current tenant (admin only)."""
    summary = get_cost_summary_db(
        db,
        current_user.tenant_id,
        task_type=task_type,
    )
    return summary
