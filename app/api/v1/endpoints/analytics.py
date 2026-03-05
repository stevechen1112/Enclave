"""
成本分析進階 API（T3-5）
提供圖表化趨勢、異常偵測、預算預警
"""
from typing import Any, List, Optional
from uuid import UUID
from datetime import datetime, timedelta, UTC

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, cast, Date
from pydantic import BaseModel

from app.api import deps
from app.api.deps_permissions import require_superuser
from app.models.user import User
from app.models.tenant import Tenant
from app.models.audit import UsageRecord
from app.crud import crud_tenant

router = APIRouter()


# ═══════════════════════════════════════════
#  Response Schemas
# ═══════════════════════════════════════════

class DailyUsage(BaseModel):
    date: str
    queries: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0


class TenantCostSummary(BaseModel):
    tenant_id: str
    tenant_name: str
    plan: Optional[str] = None
    total_cost: float = 0.0
    total_queries: int = 0
    total_tokens: int = 0
    avg_cost_per_query: float = 0.0


class CostAnomaly(BaseModel):
    tenant_id: str
    tenant_name: str
    metric: str
    current_value: float
    average_value: float
    deviation_ratio: float
    message: str


class BudgetAlert(BaseModel):
    tenant_id: str
    tenant_name: str
    resource: str
    current: float
    limit: Optional[float] = None
    usage_ratio: Optional[float] = None
    alert_type: str  # warning, exceeded


# ═══════════════════════════════════════════
#  Daily Usage Trend（圖表用）
# ═══════════════════════════════════════════

@router.get("/trends/daily", response_model=List[DailyUsage])
def daily_usage_trend(
    tenant_id: Optional[UUID] = None,
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_superuser),
) -> Any:
    """
    取得每日用量趨勢（最近 N 天）。
    若指定 tenant_id 則僅查該租戶；否則為全平台。
    """
    start = datetime.now(UTC) - timedelta(days=days)
    q = db.query(
        cast(UsageRecord.created_at, Date).label("date"),
        func.count(UsageRecord.id).label("queries"),
        func.coalesce(func.sum(UsageRecord.input_tokens), 0).label("input_tokens"),
        func.coalesce(func.sum(UsageRecord.output_tokens), 0).label("output_tokens"),
        func.coalesce(
            func.sum(UsageRecord.input_tokens + UsageRecord.output_tokens), 0
        ).label("total_tokens"),
        func.coalesce(func.sum(UsageRecord.estimated_cost_usd), 0).label("cost"),
    ).filter(UsageRecord.created_at >= start)

    if tenant_id:
        q = q.filter(UsageRecord.tenant_id == tenant_id)

    rows = (
        q.group_by(cast(UsageRecord.created_at, Date))
        .order_by(cast(UsageRecord.created_at, Date))
        .all()
    )

    return [
        DailyUsage(
            date=str(r.date),
            queries=r.queries or 0,
            input_tokens=int(r.input_tokens or 0),
            output_tokens=int(r.output_tokens or 0),
            total_tokens=int(r.total_tokens or 0),
            cost=round(float(r.cost or 0), 6),
        )
        for r in rows
    ]


# ═══════════════════════════════════════════
#  Monthly Tenant Cost Ranking
# ═══════════════════════════════════════════

@router.get("/trends/monthly-by-tenant", response_model=List[TenantCostSummary])
def monthly_cost_by_tenant(
    year: int = Query(None),
    month: int = Query(None),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_superuser),
) -> Any:
    """
    各租戶本月成本排行。
    """
    now = datetime.now(UTC)
    y = year or now.year
    m = month or now.month
    month_start = datetime(y, m, 1)
    if m == 12:
        month_end = datetime(y + 1, 1, 1)
    else:
        month_end = datetime(y, m + 1, 1)

    rows = (
        db.query(
            Tenant.id,
            Tenant.name,
            Tenant.plan,
            func.count(UsageRecord.id).label("queries"),
            func.coalesce(
                func.sum(UsageRecord.input_tokens + UsageRecord.output_tokens), 0
            ).label("tokens"),
            func.coalesce(func.sum(UsageRecord.estimated_cost_usd), 0).label("cost"),
        )
        .outerjoin(
            UsageRecord,
            (UsageRecord.tenant_id == Tenant.id)
            & (UsageRecord.created_at >= month_start)
            & (UsageRecord.created_at < month_end),
        )
        .group_by(Tenant.id, Tenant.name, Tenant.plan)
        .order_by(func.sum(UsageRecord.estimated_cost_usd).desc().nullslast())
        .all()
    )

    result = []
    for r in rows:
        queries = r.queries or 0
        cost = float(r.cost or 0)
        avg = round(cost / queries, 6) if queries > 0 else 0.0
        result.append(TenantCostSummary(
            tenant_id=str(r.id),
            tenant_name=r.name,
            plan=r.plan,
            total_cost=round(cost, 6),
            total_queries=queries,
            total_tokens=int(r.tokens or 0),
            avg_cost_per_query=avg,
        ))
    return result


# ═══════════════════════════════════════════
#  Anomaly Detection
# ═══════════════════════════════════════════

@router.get("/anomalies", response_model=List[CostAnomaly])
def detect_anomalies(
    threshold_ratio: float = Query(2.0, description="異常偵測倍數閾值（預設：平均值的 2 倍）"),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_superuser),
) -> Any:
    """
    異常偵測：找出用量明顯偏離平均的租戶。
    計算每租戶近 7 天日均 vs 前 30 天日均，找出偏離倍數超過閾值者。
    """
    now = datetime.now(UTC)
    recent_start = now - timedelta(days=7)
    baseline_start = now - timedelta(days=37)
    baseline_end = now - timedelta(days=7)

    # 近 7 天日均
    recent = (
        db.query(
            UsageRecord.tenant_id,
            (func.count(UsageRecord.id) / 7.0).label("daily_queries"),
            (func.coalesce(func.sum(UsageRecord.estimated_cost_usd), 0) / 7.0).label("daily_cost"),
        )
        .filter(UsageRecord.created_at >= recent_start)
        .group_by(UsageRecord.tenant_id)
        .all()
    )

    # 前 30 天日均
    baseline = (
        db.query(
            UsageRecord.tenant_id,
            (func.count(UsageRecord.id) / 30.0).label("daily_queries"),
            (func.coalesce(func.sum(UsageRecord.estimated_cost_usd), 0) / 30.0).label("daily_cost"),
        )
        .filter(
            UsageRecord.created_at >= baseline_start,
            UsageRecord.created_at < baseline_end,
        )
        .group_by(UsageRecord.tenant_id)
        .all()
    )

    baseline_map = {str(r.tenant_id): r for r in baseline}
    anomalies = []

    for r in recent:
        tid = str(r.tenant_id)
        bl = baseline_map.get(tid)
        if not bl:
            continue

        tenant = db.query(Tenant).filter(Tenant.id == r.tenant_id).first()
        name = tenant.name if tenant else tid

        # 查詢量異常
        if bl.daily_queries > 0:
            ratio = float(r.daily_queries) / float(bl.daily_queries)
            if ratio >= threshold_ratio:
                anomalies.append(CostAnomaly(
                    tenant_id=tid,
                    tenant_name=name,
                    metric="daily_queries",
                    current_value=round(float(r.daily_queries), 2),
                    average_value=round(float(bl.daily_queries), 2),
                    deviation_ratio=round(ratio, 2),
                    message=f"日均查詢量異常增加 {ratio:.1f} 倍",
                ))

        # 成本異常
        if bl.daily_cost > 0:
            ratio = float(r.daily_cost) / float(bl.daily_cost)
            if ratio >= threshold_ratio:
                anomalies.append(CostAnomaly(
                    tenant_id=tid,
                    tenant_name=name,
                    metric="daily_cost",
                    current_value=round(float(r.daily_cost), 6),
                    average_value=round(float(bl.daily_cost), 6),
                    deviation_ratio=round(ratio, 2),
                    message=f"日均成本異常增加 {ratio:.1f} 倍",
                ))

    return anomalies


# ═══════════════════════════════════════════
#  Budget Alerts（預算預警）
# ═══════════════════════════════════════════

@router.get("/budget-alerts", response_model=List[BudgetAlert])
def budget_alerts(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_superuser),
) -> Any:
    """
    全平台預算預警：列出所有配額接近上限或已超額的租戶。
    """
    tenants = db.query(Tenant).filter(Tenant.status == "active").all()
    alerts = []

    for tenant in tenants:
        status_data = crud_tenant.get_quota_status(db, tenant.id)
        if not status_data:
            continue

        ratio_keys = {
            "queries": ("queries_usage_ratio", "monthly_query_limit", "current_monthly_queries", "月查詢次數"),
            "tokens": ("tokens_usage_ratio", "monthly_token_limit", "current_monthly_tokens", "月 Token 量"),
            "users": ("users_usage_ratio", "max_users", "current_users", "使用者數量"),
            "documents": ("documents_usage_ratio", "max_documents", "current_documents", "文件數量"),
        }

        threshold = status_data.get("quota_alert_threshold", 0.8)

        for resource, (ratio_key, limit_key, current_key, label) in ratio_keys.items():
            ratio = status_data.get(ratio_key)
            if ratio is None:
                continue
            if ratio >= 1.0:
                alerts.append(BudgetAlert(
                    tenant_id=str(tenant.id),
                    tenant_name=tenant.name,
                    resource=resource,
                    current=status_data.get(current_key, 0),
                    limit=status_data.get(limit_key),
                    usage_ratio=ratio,
                    alert_type="exceeded",
                ))
            elif ratio >= threshold:
                alerts.append(BudgetAlert(
                    tenant_id=str(tenant.id),
                    tenant_name=tenant.name,
                    resource=resource,
                    current=status_data.get(current_key, 0),
                    limit=status_data.get(limit_key),
                    usage_ratio=ratio,
                    alert_type="warning",
                ))

    # 依嚴重程度排序
    alerts.sort(key=lambda a: (0 if a.alert_type == "exceeded" else 1, -(a.usage_ratio or 0)))
    return alerts
