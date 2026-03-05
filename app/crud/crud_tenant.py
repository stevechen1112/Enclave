from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime, UTC
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.tenant import Tenant
from app.models.user import User
from app.models.document import Document
from app.models.audit import UsageRecord
from app.schemas.tenant import TenantCreate, TenantUpdate, PLAN_QUOTAS


def get(db: Session, tenant_id: UUID) -> Optional[Tenant]:
    return db.query(Tenant).filter(Tenant.id == tenant_id).first()


def get_by_name(db: Session, name: str) -> Optional[Tenant]:
    return db.query(Tenant).filter(Tenant.name == name).first()


def get_multi(db: Session, skip: int = 0, limit: int = 100) -> List[Tenant]:
    return db.query(Tenant).offset(skip).limit(limit).all()


def create(db: Session, *, obj_in: TenantCreate) -> Tenant:
    plan = obj_in.plan or "free"
    defaults = PLAN_QUOTAS.get(plan, PLAN_QUOTAS["free"])
    db_obj = Tenant(
        name=obj_in.name,
        plan=plan,
        status=obj_in.status or "active",
        max_users=obj_in.max_users if obj_in.max_users is not None else defaults.get("max_users"),
        max_documents=obj_in.max_documents if obj_in.max_documents is not None else defaults.get("max_documents"),
        max_storage_mb=obj_in.max_storage_mb if obj_in.max_storage_mb is not None else defaults.get("max_storage_mb"),
        monthly_query_limit=obj_in.monthly_query_limit if obj_in.monthly_query_limit is not None else defaults.get("monthly_query_limit"),
        monthly_token_limit=obj_in.monthly_token_limit if obj_in.monthly_token_limit is not None else defaults.get("monthly_token_limit"),
        quota_alert_threshold=obj_in.quota_alert_threshold if obj_in.quota_alert_threshold is not None else 0.8,
        quota_alert_email=obj_in.quota_alert_email,
    )
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj


def update(db: Session, *, db_obj: Tenant, obj_in: TenantUpdate) -> Tenant:
    update_data = obj_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_obj, field, value)
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj


# ═══════════════════════════════════════════
#  Quota 查詢與檢查
# ═══════════════════════════════════════════

def _month_start() -> datetime:
    """取得當月第一天"""
    now = datetime.now(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def get_current_usage(db: Session, tenant_id: UUID) -> Dict[str, Any]:
    """取得租戶目前使用量"""
    month_start = _month_start()

    user_count = db.query(func.count(User.id)).filter(
        User.tenant_id == tenant_id, User.status == "active"
    ).scalar() or 0

    doc_count = db.query(func.count(Document.id)).filter(
        Document.tenant_id == tenant_id
    ).scalar() or 0

    # 月度查詢次數和 token 數
    monthly = db.query(
        func.count(UsageRecord.id).label("queries"),
        func.coalesce(
            func.sum(UsageRecord.input_tokens + UsageRecord.output_tokens), 0
        ).label("tokens"),
    ).filter(
        UsageRecord.tenant_id == tenant_id,
        UsageRecord.created_at >= month_start,
    ).first()

    return {
        "current_users": user_count,
        "current_documents": doc_count,
        "current_storage_mb": 0.0,  # TODO: 從文件大小累計
        "current_monthly_queries": monthly.queries or 0,
        "current_monthly_tokens": int(monthly.tokens or 0),
    }


def get_quota_status(db: Session, tenant_id: UUID) -> Dict[str, Any]:
    """取得租戶完整配額狀態（含使用量與使用率）"""
    tenant = get(db, tenant_id)
    if not tenant:
        return {}

    usage = get_current_usage(db, tenant_id)
    warnings: List[str] = []
    is_over = False
    threshold = tenant.quota_alert_threshold or 0.8

    def _ratio(current, limit):
        if limit is None or limit == 0:
            return None
        return round(current / limit, 4)

    ratios = {
        "users": _ratio(usage["current_users"], tenant.max_users),
        "documents": _ratio(usage["current_documents"], tenant.max_documents),
        "storage": _ratio(usage["current_storage_mb"], tenant.max_storage_mb),
        "queries": _ratio(usage["current_monthly_queries"], tenant.monthly_query_limit),
        "tokens": _ratio(usage["current_monthly_tokens"], tenant.monthly_token_limit),
    }

    labels = {
        "users": ("使用者", tenant.max_users),
        "documents": ("文件", tenant.max_documents),
        "storage": ("儲存空間", tenant.max_storage_mb),
        "queries": ("月查詢次數", tenant.monthly_query_limit),
        "tokens": ("月 Token 量", tenant.monthly_token_limit),
    }

    for key, ratio in ratios.items():
        if ratio is None:
            continue
        label, limit = labels[key]
        if ratio >= 1.0:
            is_over = True
            warnings.append(f"{label}已超過配額上限 ({limit})")
        elif ratio >= threshold:
            warnings.append(f"{label}已達配額 {int(ratio*100)}%（上限 {limit}）")

    return {
        "tenant_id": str(tenant_id),
        "plan": tenant.plan,
        "max_users": tenant.max_users,
        "max_documents": tenant.max_documents,
        "max_storage_mb": tenant.max_storage_mb,
        "monthly_query_limit": tenant.monthly_query_limit,
        "monthly_token_limit": tenant.monthly_token_limit,
        "quota_alert_threshold": threshold,
        **usage,
        "users_usage_ratio": ratios["users"],
        "documents_usage_ratio": ratios["documents"],
        "storage_usage_ratio": ratios["storage"],
        "queries_usage_ratio": ratios["queries"],
        "tokens_usage_ratio": ratios["tokens"],
        "is_over_quota": is_over,
        "quota_warnings": warnings,
    }


def check_quota(db: Session, tenant_id: UUID, resource: str) -> Dict[str, Any]:
    """
    檢查特定資源是否超額。
    resource: "user", "document", "query", "token"
    回傳 {"allowed": bool, "message": str, "current": int, "limit": int|None}
    """
    tenant = get(db, tenant_id)
    if not tenant:
        return {"allowed": False, "message": "租戶不存在"}

    usage = get_current_usage(db, tenant_id)

    checks = {
        "user": (usage["current_users"], tenant.max_users, "使用者數量"),
        "document": (usage["current_documents"], tenant.max_documents, "文件數量"),
        "query": (usage["current_monthly_queries"], tenant.monthly_query_limit, "月查詢次數"),
        "token": (usage["current_monthly_tokens"], tenant.monthly_token_limit, "月 Token 量"),
    }

    if resource not in checks:
        return {"allowed": True, "message": "未知資源類型，不做限制"}

    current, limit, label = checks[resource]
    if limit is None:
        return {"allowed": True, "message": f"{label}無上限", "current": current, "limit": None}
    if current >= limit:
        return {
            "allowed": False,
            "message": f"{label}已達上限 {limit}，目前 {current}",
            "current": current,
            "limit": limit,
        }
    return {"allowed": True, "message": "OK", "current": current, "limit": limit}
