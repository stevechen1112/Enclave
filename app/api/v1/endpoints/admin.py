"""
地端版管理後台 API（Superuser 專用）
P9-1/P9-2: 移除跨租戶管理、訂閱方案、配額管理。
保留：單一組織儀表板、使用者管理、系統健康監控。
"""
from typing import Any, List, Optional
from uuid import UUID
from datetime import datetime, timedelta, UTC

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, text

from app.api import deps
from app.api.deps_permissions import require_superuser
from app.models.user import User
from app.models.tenant import Tenant
from app.models.document import Document
from app.models.audit import AuditLog, UsageRecord
from app.models.chat import Conversation
from app.schemas.admin import AdminUserInfo, OrgDashboard, SystemHealth

router = APIRouter()


# ===============================================
#  Organisation Dashboard (single-org)
# ===============================================

@router.get("/dashboard", response_model=OrgDashboard)
def org_dashboard(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_superuser),
) -> Any:
    """組織系統儀表板（地端單一組織版）"""
    tid = current_user.tenant_id

    org = db.query(Tenant).filter(Tenant.id == tid).first()
    org_name = org.name if org else "My Organization"

    total_users = db.query(func.count(User.id)).filter(User.tenant_id == tid).scalar() or 0
    active_users = (
        db.query(func.count(User.id))
        .filter(User.tenant_id == tid, User.status == "active")
        .scalar() or 0
    )
    total_documents = (
        db.query(func.count(Document.id)).filter(Document.tenant_id == tid).scalar() or 0
    )
    total_conversations = (
        db.query(func.count(Conversation.id)).filter(Conversation.tenant_id == tid).scalar() or 0
    )

    usage_agg = (
        db.query(
            func.count(UsageRecord.id).label("total_actions"),
            func.coalesce(func.sum(UsageRecord.estimated_cost_usd), 0).label("total_cost"),
        )
        .filter(UsageRecord.tenant_id == tid)
        .first()
    )
    total_actions = usage_agg.total_actions or 0
    total_cost = float(usage_agg.total_cost or 0)

    seven_days_ago = datetime.now(UTC) - timedelta(days=7)
    daily_rows = (
        db.query(
            func.date(UsageRecord.created_at).label("date"),
            func.count(UsageRecord.id).label("count"),
            func.coalesce(func.sum(UsageRecord.estimated_cost_usd), 0).label("cost"),
        )
        .filter(UsageRecord.tenant_id == tid, UsageRecord.created_at >= seven_days_ago)
        .group_by(func.date(UsageRecord.created_at))
        .order_by(func.date(UsageRecord.created_at))
        .all()
    )
    daily_actions = [
        {"date": str(r.date), "count": r.count, "cost": float(r.cost)}
        for r in daily_rows
    ]

    top_rows = (
        db.query(
            User.email,
            func.count(UsageRecord.id).label("actions"),
            func.coalesce(func.sum(UsageRecord.estimated_cost_usd), 0).label("cost"),
        )
        .join(UsageRecord, UsageRecord.user_id == User.id)
        .filter(User.tenant_id == tid)
        .group_by(User.email)
        .order_by(func.sum(UsageRecord.estimated_cost_usd).desc())
        .limit(5)
        .all()
    )
    top_users = [
        {"email": r.email, "actions": r.actions, "cost": float(r.cost)}
        for r in top_rows
    ]

    return OrgDashboard(
        org_name=org_name,
        total_users=total_users,
        active_users=active_users,
        total_documents=total_documents,
        total_conversations=total_conversations,
        total_actions=total_actions,
        total_cost=total_cost,
        daily_actions=daily_actions,
        top_users=top_users,
    )


# ===============================================
#  User Management (within single org)
# ===============================================

@router.get("/users", response_model=List[AdminUserInfo])
def search_users(
    search: Optional[str] = None,
    role: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_superuser),
) -> Any:
    """組織內用戶搜尋"""
    from app.models.permission import Department

    tid = current_user.tenant_id
    q = db.query(User).filter(User.tenant_id == tid)
    if search:
        q = q.filter(
            (User.email.ilike(f"%{search}%")) | (User.full_name.ilike(f"%{search}%"))
        )
    if role:
        q = q.filter(User.role == role)

    users = q.order_by(User.created_at.desc()).offset(skip).limit(limit).all()

    result = []
    for u in users:
        dept = None
        if u.department_id:
            dept_obj = db.query(Department).filter(Department.id == u.department_id).first()
            dept = dept_obj.name if dept_obj else None

        result.append(AdminUserInfo(
            id=str(u.id),
            email=u.email,
            full_name=u.full_name,
            role=u.role,
            status=u.status,
            tenant_id=str(u.tenant_id),
            department_name=dept,
            created_at=u.created_at,
        ))
    return result


@router.post("/users/invite")
def invite_user(
    payload: dict,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_superuser),
) -> Any:
    """邀請新使用者加入組織"""
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
        role=payload.get("role", "member"),
        tenant_id=current_user.tenant_id,
        status="active",
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return AdminUserInfo(
        id=str(new_user.id),
        email=new_user.email,
        full_name=new_user.full_name,
        role=new_user.role,
        status=new_user.status,
        tenant_id=str(new_user.tenant_id),
        department_name=None,
        created_at=new_user.created_at,
    )


@router.put("/users/{user_id}")
def update_user(
    user_id: UUID,
    payload: dict,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_superuser),
) -> Any:
    """更新組織內使用者資料"""
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
    return {"updated": True, "user_id": str(user.id)}


@router.delete("/users/{user_id}")
def deactivate_user(
    user_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_superuser),
) -> Any:
    """停用組織內使用者"""
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
    return {"deactivated": True, "user_id": str(user.id)}


# ===============================================
#  System Health
# ===============================================

@router.get("/system/health", response_model=SystemHealth)
def system_health(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_superuser),
) -> Any:
    """系統健康狀態"""
    import sys
    import time
    import redis as redis_lib

    start = time.time()

    db_status = "healthy"
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_status = "unhealthy"

    redis_status = "healthy"
    try:
        from app.config import settings
        r = redis_lib.Redis.from_url(settings.CELERY_BROKER_URL)
        r.ping()
        r.close()
    except Exception:
        redis_status = "unavailable"

    overall = "healthy" if db_status == "healthy" else "degraded"

    return SystemHealth(
        status=overall,
        database=db_status,
        redis=redis_status,
        uptime_seconds=round(time.time() - start, 3),
        python_version=sys.version.split()[0],
        active_connections=0,
    )


# ===============================================
#  Quota Management — 已移除（地端版不需要 SaaS 配額管理）
# ===============================================

# ===============================================
#  Security Config — 已移除（地端版不需要多租戶安全組態）
# ===============================================
