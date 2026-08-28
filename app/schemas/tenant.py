from typing import Optional
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


# Shared properties
class TenantBase(BaseModel):
    name: Optional[str] = None
    plan: Optional[str] = None  # pilot, team, business, enterprise（遺留：free, pro）
    status: Optional[str] = None  # active, suspended


# Properties to receive via API on creation
class TenantCreate(TenantBase):
    name: str
    max_users: Optional[int] = None
    max_documents: Optional[int] = None
    max_storage_mb: Optional[int] = None
    monthly_query_limit: Optional[int] = None
    monthly_token_limit: Optional[int] = None
    monthly_cost_limit_usd: Optional[float] = Field(default=None, ge=0)
    quota_alert_threshold: Optional[float] = 0.8
    quota_alert_email: Optional[str] = None


# Properties to receive via API on update
class TenantUpdate(TenantBase):
    max_users: Optional[int] = None
    max_documents: Optional[int] = None
    max_storage_mb: Optional[int] = None
    monthly_query_limit: Optional[int] = None
    monthly_token_limit: Optional[int] = None
    monthly_cost_limit_usd: Optional[float] = Field(default=None, ge=0)
    quota_alert_threshold: Optional[float] = None
    quota_alert_email: Optional[str] = None


class TenantInDBBase(TenantBase):
    id: Optional[UUID] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    max_users: Optional[int] = None
    max_documents: Optional[int] = None
    max_storage_mb: Optional[int] = None
    monthly_query_limit: Optional[int] = None
    monthly_token_limit: Optional[int] = None
    monthly_cost_limit_usd: Optional[float] = Field(default=None, ge=0)
    quota_alert_threshold: Optional[float] = 0.8
    quota_alert_email: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# Additional properties to return via API
class Tenant(TenantInDBBase):
    pass


# Quota status response
class QuotaStatus(BaseModel):
    tenant_id: str
    plan: Optional[str] = None
    # 配額設定
    max_users: Optional[int] = None
    max_documents: Optional[int] = None
    max_storage_mb: Optional[int] = None
    monthly_query_limit: Optional[int] = None
    monthly_token_limit: Optional[int] = None
    monthly_cost_limit_usd: Optional[float] = Field(default=None, ge=0)
    quota_alert_threshold: float = 0.8
    # 目前使用量
    current_users: int = 0
    current_documents: int = 0
    current_storage_mb: float = 0.0
    current_monthly_queries: int = 0
    current_monthly_tokens: int = 0
    current_monthly_cost_usd: float = 0.0
    # 使用率 (0~1)
    users_usage_ratio: Optional[float] = None
    documents_usage_ratio: Optional[float] = None
    storage_usage_ratio: Optional[float] = None
    queries_usage_ratio: Optional[float] = None
    tokens_usage_ratio: Optional[float] = None
    cost_usage_ratio: Optional[float] = None
    # 是否超額
    is_over_quota: bool = False
    quota_warnings: list = []


# Quota update request (admin only)
class QuotaUpdate(BaseModel):
    max_users: Optional[int] = None
    max_documents: Optional[int] = None
    max_storage_mb: Optional[int] = None
    monthly_query_limit: Optional[int] = None
    monthly_token_limit: Optional[int] = None
    monthly_cost_limit_usd: Optional[float] = Field(default=None, ge=0)
    quota_alert_threshold: Optional[float] = None
    quota_alert_email: Optional[str] = None


# Plan-based default quotas
# CG-QUOTA 方案矩陣：pilot/team/business/enterprise 對齊
# docs/CLOUD_AND_COMMERCIALIZATION_PLAN.md §3.3（數字為起始建議，上線前以
# Design Partner 真實用量校正）；free/pro 為早期遺留方案名，保留相容。
PLAN_QUOTAS = {
    "pilot": {
        "max_users": 10,
        "max_documents": 200,
        "max_storage_mb": 500,
        "monthly_query_limit": 500,
        "monthly_token_limit": 2_000_000,
        "monthly_cost_limit_usd": 50.0,
    },
    "team": {
        "max_users": 50,
        "max_documents": 2000,
        "max_storage_mb": 5000,
        "monthly_query_limit": 5000,
        "monthly_token_limit": 40_000_000,
        "monthly_cost_limit_usd": 500.0,
    },
    "business": {
        "max_users": 200,
        "max_documents": 20000,
        "max_storage_mb": 50000,
        "monthly_query_limit": 50000,
        "monthly_token_limit": 400_000_000,
        "monthly_cost_limit_usd": 5000.0,
    },
    "enterprise": {
        "max_users": None,       # 合約制（無限制）
        "max_documents": None,
        "max_storage_mb": None,
        "monthly_query_limit": None,
        "monthly_token_limit": None,
        "monthly_cost_limit_usd": None,
    },
    # 遺留方案名（既有租戶相容；新租戶請用 pilot/team/business）
    "free": {
        "max_users": 5,
        "max_documents": 20,
        "max_storage_mb": 100,
        "monthly_query_limit": 500,
        "monthly_token_limit": 500000,
        "monthly_cost_limit_usd": 10.0,
    },
    "pro": {
        "max_users": 50,
        "max_documents": 200,
        "max_storage_mb": 1000,
        "monthly_query_limit": 5000,
        "monthly_token_limit": 5000000,
        "monthly_cost_limit_usd": 200.0,
    },
}


class SecurityConfig(BaseModel):
    tenant_id: Optional[str] = None
    isolation_level: str = "standard"
    require_mfa: bool = False
    ip_whitelist: Optional[str] = ""


class SecurityConfigUpdate(BaseModel):
    isolation_level: Optional[str] = None
    require_mfa: Optional[bool] = None
    ip_whitelist: Optional[str] = None


class TenantInDB(TenantInDBBase):
    pass
