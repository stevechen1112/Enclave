"""
Company Self-Service API — /api/v1/company
T3-2: 租戶自助管理端點（Owner/Admin 使用）

  GET  /company/dashboard        — 公司儀表板
  GET  /company/profile          — 公司資訊
  GET  /company/quota            — 配額狀態
  POST /company/users/invite     — 邀請新成員
  GET  /company/users            — 列出公司成員
  PUT  /company/users/{user_id}  — 更新成員資料
  DELETE /company/users/{user_id} — 停用成員
  GET  /company/usage/summary    — 用量摘要
  GET  /company/usage/by-user    — 每位使用者用量
"""
from typing import Any, List, Optional
from uuid import UUID
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel

from app.api import deps
from app.api.deps_permissions import require_admin
from app.crud import crud_tenant, crud_audit
from app.models.user import User
from app.models.tenant import Tenant
from app.models.audit import UsageRecord
from app.services.deployment_mode import (
    DEPLOYMENT_MODE_GPU,
    DEPLOYMENT_MODE_NOGPU,
    get_deployment_mode,
    resolve_runtime_profiles,
    set_deployment_mode,
)

router = APIRouter()


class DeploymentModeUpdate(BaseModel):
    mode: str


def _require_same_tenant(current_user: User, target_tenant_id: UUID) -> None:
    """Check that the current user (non-superuser) belongs to the same tenant."""
    if not current_user.is_superuser and current_user.tenant_id != target_tenant_id:
        raise HTTPException(status_code=403, detail="Access denied")


# ─── Dashboard ──────────────────────────────────────────────────────────────

@router.get("/dashboard")
def company_dashboard(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_admin),
) -> Any:
    """公司儀表板：使用者數、配額狀態、最近活動"""
    tid = current_user.tenant_id
    tenant = db.query(Tenant).filter(Tenant.id == tid).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    user_count = (
        db.query(func.count(User.id))
        .filter(User.tenant_id == tid, User.status == "active")
        .scalar() or 0
    )
    quota_status = crud_tenant.get_quota_status(db, tid)

    return {
        "company_name": tenant.name,
        "user_count": user_count,
        "quota_status": quota_status,
        "plan": tenant.plan,
    }


# ─── Profile ────────────────────────────────────────────────────────────────

@router.get("/profile")
def company_profile(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_admin),
) -> Any:
    """公司資訊"""
    tid = current_user.tenant_id
    tenant = db.query(Tenant).filter(Tenant.id == tid).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    return {
        "id": str(tenant.id),
        "name": tenant.name,
        "plan": tenant.plan,
        "status": tenant.status,
        "created_at": tenant.created_at.isoformat() if tenant.created_at else None,
    }


# ─── Quota ──────────────────────────────────────────────────────────────────

@router.get("/quota")
def company_quota(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_admin),
) -> Any:
    """公司配額狀態"""
    return crud_tenant.get_quota_status(db, current_user.tenant_id)


@router.get("/deployment-mode")
def get_company_deployment_mode(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_admin),
) -> Any:
    """取得目前部署模式與生效中的 LLM preset。"""
    mode = get_deployment_mode(db)
    profiles = resolve_runtime_profiles(db)
    return {
        "mode": mode,
        "supported_modes": [DEPLOYMENT_MODE_NOGPU, DEPLOYMENT_MODE_GPU],
        "profiles": profiles,
        "updated_by": str(current_user.id),
    }


@router.put("/deployment-mode")
def update_company_deployment_mode(
    payload: DeploymentModeUpdate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_admin),
) -> Any:
    """切換部署模式：nogpu（沿用現有設定）/ gpu（固定 Qwen3 + bge-m3）。"""
    try:
        mode = set_deployment_mode(db, payload.mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    profiles = resolve_runtime_profiles(db)
    return {
        "ok": True,
        "mode": mode,
        "profiles": profiles,
        "message": "部署模式已更新，下一次請求立即生效",
        "updated_by": str(current_user.id),
    }


# ─── User Management ────────────────────────────────────────────────────────

@router.post("/users/invite")
def invite_member(
    payload: dict,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_admin),
) -> Any:
    """邀請新成員加入公司"""
    from app.core.security import get_password_hash

    email = payload.get("email", "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")

    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(status_code=409, detail="此 Email 已被使用")

    new_user = User(
        email=email,
        full_name=payload.get("full_name", ""),
        hashed_password=get_password_hash(payload.get("password", "changeme123")),
        role=payload.get("role", "employee"),
        tenant_id=current_user.tenant_id,
        status="active",
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {
        "id": str(new_user.id),
        "email": new_user.email,
        "full_name": new_user.full_name,
        "role": new_user.role,
        "status": new_user.status,
        "tenant_id": str(new_user.tenant_id),
        "created_at": new_user.created_at.isoformat() if new_user.created_at else None,
    }


@router.get("/users")
def list_members(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_admin),
) -> Any:
    """列出公司成員"""
    users = (
        db.query(User)
        .filter(User.tenant_id == current_user.tenant_id)
        .order_by(User.created_at.asc())
        .all()
    )
    return [
        {
            "id": str(u.id),
            "email": u.email,
            "full_name": u.full_name,
            "role": u.role,
            "status": u.status,
        }
        for u in users
    ]


@router.put("/users/{user_id}")
def update_member(
    user_id: UUID,
    payload: dict,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_admin),
) -> Any:
    """更新成員資料（角色、狀態等）"""
    user = db.query(User).filter(
        User.id == user_id,
        User.tenant_id == current_user.tenant_id,
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="找不到使用者")

    for field in ("full_name", "role", "status"):
        if field in payload:
            setattr(user, field, payload[field])

    db.commit()
    db.refresh(user)
    return {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "status": user.status,
    }


@router.delete("/users/{user_id}")
def deactivate_member(
    user_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_admin),
) -> Any:
    """停用成員帳號"""
    user = db.query(User).filter(
        User.id == user_id,
        User.tenant_id == current_user.tenant_id,
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="找不到使用者")
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="不能停用自己的帳號")

    user.status = "inactive"
    db.commit()
    return {"message": f"已停用使用者 {user.email}", "user_id": str(user.id)}


# ─── Usage ──────────────────────────────────────────────────────────────────

@router.get("/usage/summary")
def company_usage_summary(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_admin),
) -> Any:
    """公司用量摘要"""
    summary = crud_audit.get_usage_summary(
        db,
        tenant_id=current_user.tenant_id,
        start_date=None,
        end_date=None,
    )
    return summary


@router.get("/usage/by-user")
def company_usage_by_user(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_admin),
) -> Any:
    """每位使用者的用量統計"""
    rows = (
        db.query(
            User.email,
            User.full_name,
            func.count(UsageRecord.id).label("total_actions"),
            func.coalesce(func.sum(UsageRecord.input_tokens), 0).label("total_input_tokens"),
            func.coalesce(func.sum(UsageRecord.output_tokens), 0).label("total_output_tokens"),
            func.coalesce(func.sum(UsageRecord.estimated_cost_usd), 0).label("total_cost"),
        )
        .join(UsageRecord, UsageRecord.user_id == User.id, isouter=True)
        .filter(User.tenant_id == current_user.tenant_id)
        .group_by(User.id, User.email, User.full_name)
        .order_by(func.count(UsageRecord.id).desc())
        .all()
    )
    return [
        {
            "email": r.email,
            "full_name": r.full_name,
            "total_actions": r.total_actions or 0,
            "total_input_tokens": r.total_input_tokens or 0,
            "total_output_tokens": r.total_output_tokens or 0,
            "total_cost": float(r.total_cost or 0),
        }
        for r in rows
    ]
