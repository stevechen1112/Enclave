from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime, UTC
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.tenant import Tenant
from app.models.user import User
from app.models.document import Document
from app.models.audit import UsageRecord
from app.config import settings
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

    # ADR-013：租戶建立即配發空 sidecar binding（各 pack NULL＝未啟用），
    # 讓 binding 解析永遠 fail-closed 有據可依；pack 啟用時再寫入歸屬 ID
    try:
        from app.services.sidecar_binding import ensure_binding

        ensure_binding(db, db_obj.id)
        db.commit()
    except Exception:
        db.rollback()
        raise
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
        Document.tenant_id == tenant_id,
        Document.tombstoned_at.is_(None),
    ).scalar() or 0

    # CG-QUOTA 儲存軸：以文件 file_size 累計（bytes → MB）
    storage_bytes = db.query(
        func.coalesce(func.sum(Document.file_size), 0)
    ).filter(
        Document.tenant_id == tenant_id,
        Document.tombstoned_at.is_(None),
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
        "current_storage_mb": round(storage_bytes / (1024 * 1024), 2),
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


def check_storage_quota(
    db: Session, tenant_id: UUID, additional_bytes: int = 0
) -> Dict[str, Any]:
    """檢查儲存配額（含即將上傳的 additional_bytes）。"""
    tenant = get(db, tenant_id)
    if not tenant:
        return {"allowed": False, "message": "租戶不存在"}

    usage = get_current_usage(db, tenant_id)
    current_mb = usage["current_storage_mb"]
    add_mb = additional_bytes / (1024 * 1024)
    limit = tenant.max_storage_mb
    projected = current_mb + add_mb

    if limit is None:
        return {
            "allowed": True,
            "message": "儲存空間無上限",
            "current": current_mb,
            "limit": None,
            "projected_mb": round(projected, 2),
        }
    if projected > limit:
        return {
            "allowed": False,
            "message": f"儲存空間已達上限 {limit} MB，目前 {current_mb:.2f} MB，本次需 {add_mb:.2f} MB",
            "current": current_mb,
            "limit": limit,
            "projected_mb": round(projected, 2),
        }
    return {
        "allowed": True,
        "message": "OK",
        "current": current_mb,
        "limit": limit,
        "projected_mb": round(projected, 2),
    }


def check_quota(db: Session, tenant_id: UUID, resource: str) -> Dict[str, Any]:
    """
    檢查特定資源是否超額。
    resource: "user", "document", "storage", "query", "token"
    回傳 {"allowed": bool, "message": str, "current": int, "limit": int|None}
    """
    tenant = get(db, tenant_id)
    if not tenant:
        return {"allowed": False, "message": "租戶不存在"}

    usage = get_current_usage(db, tenant_id)

    checks = {
        "user": (usage["current_users"], tenant.max_users, "使用者數量"),
        "document": (usage["current_documents"], tenant.max_documents, "文件數量"),
        "storage": (usage["current_storage_mb"], tenant.max_storage_mb, "儲存空間"),
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


def _apply_plan_fields(tenant: Tenant, plan: str) -> None:
    if plan not in PLAN_QUOTAS:
        raise ValueError(f"unknown plan: {plan}")
    defaults = PLAN_QUOTAS[plan]
    tenant.plan = plan
    tenant.max_users = defaults.get("max_users")
    tenant.max_documents = defaults.get("max_documents")
    tenant.max_storage_mb = defaults.get("max_storage_mb")
    tenant.monthly_query_limit = defaults.get("monthly_query_limit")
    tenant.monthly_token_limit = defaults.get("monthly_token_limit")


def lock_and_check_storage_quota(
    db: Session, tenant_id: UUID, additional_bytes: int
) -> Dict[str, Any]:
    """FOR UPDATE 鎖租戶後檢查儲存配額（與後續 create 同一 transaction，防 TOCTOU）。"""
    locked = (
        db.query(Tenant)
        .filter(Tenant.id == tenant_id)
        .with_for_update()
        .first()
    )
    if not locked:
        db.rollback()
        return {"allowed": False, "message": "租戶不存在"}
    result = check_storage_quota(db, tenant_id, additional_bytes)
    if not result.get("allowed", True):
        db.rollback()
    return result


def reserve_chat_quota(
    db: Session,
    tenant_id: UUID,
    user_id: UUID,
) -> Dict[str, Any]:
    """原子性預留一次聊天查詢配額（FOR UPDATE 鎖租戶列，插入 UsageRecord 後 commit）。

    解決 check→process→log 之間的 TOCTOU：並發請求無法全部通過前置檢查後集體超額。
    Token 軸：預留時寫入 CHAT_TOKEN_RESERVE_ESTIMATE，finalize 改為實際 token。
    """
    reserve_tokens = int(getattr(settings, "CHAT_TOKEN_RESERVE_ESTIMATE", 4000) or 4000)

    locked = (
        db.query(Tenant)
        .filter(Tenant.id == tenant_id)
        .with_for_update()
        .first()
    )
    if not locked:
        return {"allowed": False, "message": "租戶不存在", "usage_record_id": None}

    usage = get_current_usage(db, tenant_id)
    token_limit = locked.monthly_token_limit
    if token_limit is not None:
        projected_tokens = usage["current_monthly_tokens"] + reserve_tokens
        if projected_tokens > token_limit:
            db.rollback()
            return {
                "allowed": False,
                "message": f"月 Token 量已達上限 {token_limit}，目前 {usage['current_monthly_tokens']}",
                "current": usage["current_monthly_tokens"],
                "limit": token_limit,
                "usage_record_id": None,
                "axis": "token",
            }

    query_check = check_quota(db, tenant_id, "query")
    if not query_check.get("allowed", True):
        db.rollback()
        return {**query_check, "usage_record_id": None, "axis": "query"}

    record = UsageRecord(
        tenant_id=tenant_id,
        user_id=user_id,
        action_type="chat_query",
        input_tokens=reserve_tokens,
        output_tokens=0,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return {
        "allowed": True,
        "message": "OK",
        "usage_record_id": record.id,
        "current": (query_check.get("current") or 0) + 1,
        "limit": query_check.get("limit"),
    }


def cancel_chat_quota_reservation(db: Session, usage_record_id: UUID) -> None:
    """釋放未完成的聊天配額預留（例如對話驗證失敗）。"""
    record = db.query(UsageRecord).filter(UsageRecord.id == usage_record_id).first()
    if record:
        db.delete(record)
        db.commit()


def update_quota(db: Session, tenant_id: UUID, quota_data: Dict[str, Any]) -> Optional[Tenant]:
    """更新租戶配額設定。"""
    tenant = get(db, tenant_id)
    if not tenant:
        return None
    for field in (
        "max_users", "max_documents", "max_storage_mb",
        "monthly_query_limit", "monthly_token_limit",
        "quota_alert_threshold", "quota_alert_email",
    ):
        if field in quota_data and quota_data[field] is not None:
            setattr(tenant, field, quota_data[field])
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return tenant


def apply_plan_quota(db: Session, tenant_id: UUID, plan: str) -> Optional[Tenant]:
    """套用方案預設配額。"""
    tenant = get(db, tenant_id)
    if not tenant:
        return None
    if plan not in PLAN_QUOTAS:
        return None
    _apply_plan_fields(tenant, plan)
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return tenant


VALID_ISOLATION_LEVELS = {"standard", "enhanced", "strict"}


def get_security_config(db: Session, tenant_id: UUID) -> Optional[Dict[str, Any]]:
    tenant = get(db, tenant_id)
    if not tenant:
        return None
    return {
        "tenant_id": str(tenant_id),
        "isolation_level": tenant.isolation_level or "standard",
        "require_mfa": tenant.require_mfa or False,
        "ip_whitelist": tenant.ip_whitelist or "",
    }


def update_security_config(db: Session, tenant_id: UUID, config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    tenant = get(db, tenant_id)
    if not tenant:
        return None
    if "isolation_level" in config:
        level = config["isolation_level"]
        if level not in VALID_ISOLATION_LEVELS:
            raise ValueError(f"invalid_isolation_level:{level}")
        tenant.isolation_level = level
    if "require_mfa" in config:
        tenant.require_mfa = bool(config["require_mfa"])
    if "ip_whitelist" in config:
        tenant.ip_whitelist = config["ip_whitelist"]
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return get_security_config(db, tenant_id)
