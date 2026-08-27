"""Authenticated telemetry and admin removal-gate report for legacy surfaces."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.api import deps
from app.api.deps_permissions import require_admin
from app.models.audit import AuditLog
from app.models.user import User
from app.platform.deprecations import SURFACES, get_deprecation_surface

router = APIRouter(prefix="/deprecations")


class LegacyUsageRequest(BaseModel):
    key: str = Field(min_length=1, max_length=100)
    client_path: str | None = Field(default=None, max_length=500)


@router.post("/usage", status_code=202)
def record_legacy_usage(
    payload: LegacyUsageRequest,
    request: Request,
    db: Annotated[Session, Depends(deps.get_db)],
    current_user: Annotated[User, Depends(deps.get_current_active_user)],
) -> dict[str, bool]:
    surface = get_deprecation_surface(payload.key)
    if surface is None:
        raise HTTPException(status_code=400, detail="unknown deprecation surface")
    db.add(
        AuditLog(
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            action="legacy_surface_used",
            target_type="legacy_surface",
            target_id=surface.key,
            ip_address=request.client.host if request.client else None,
            detail_json={
                "kind": surface.kind,
                "legacy_path": surface.legacy_path,
                "replacement_path": surface.replacement_path,
                "client_path": payload.client_path,
            },
        )
    )
    db.commit()
    return {"recorded": True}


@router.get("")
def deprecation_report(
    db: Annotated[Session, Depends(deps.get_db)],
    current_user: Annotated[User, Depends(require_admin)],
) -> list[dict[str, Any]]:
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=30)
    aggregate = {
        str(target_id): {"hit_count_30d": int(count), "last_used_at": last_used}
        for target_id, count, last_used in (
            db.query(
                AuditLog.target_id,
                func.sum(case((AuditLog.created_at >= cutoff, 1), else_=0)),
                func.max(AuditLog.created_at),
            )
            .filter(
                AuditLog.tenant_id == current_user.tenant_id,
                AuditLog.action == "legacy_surface_used",
            )
            .group_by(AuditLog.target_id)
            .all()
        )
    }
    rows = []
    for surface in SURFACES:
        usage = aggregate.get(surface.key, {})
        last_used_at = usage.get("last_used_at")
        rows.append(
            {
                "key": surface.key,
                "kind": surface.kind,
                "legacy_path": surface.legacy_path,
                "replacement_path": surface.replacement_path,
                "stage": surface.stage,
                "observation_started_at": surface.observation_started_at,
                "eligible_after": surface.eligible_after,
                "hit_count_30d": usage.get("hit_count_30d", 0),
                "last_used_at": last_used_at,
                "removal_eligible": surface.removal_eligible(
                    last_used_at=last_used_at, now=now
                ),
            }
        )
    return rows
