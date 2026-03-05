from typing import Optional
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, ConfigDict


# Shared properties
class TenantBase(BaseModel):
    name: Optional[str] = None
    plan: Optional[str] = None  # free, pro, enterprise
    status: Optional[str] = None  # active, suspended


# Properties to receive via API on creation
class TenantCreate(TenantBase):
    name: str
    max_users: Optional[int] = None
    max_documents: Optional[int] = None
    max_storage_mb: Optional[int] = None
    monthly_query_limit: Optional[int] = None
    monthly_token_limit: Optional[int] = None
    quota_alert_threshold: Optional[float] = 0.8
    quota_alert_email: Optional[str] = None


# Properties to receive via API on update
class TenantUpdate(TenantBase):
    max_users: Optional[int] = None
    max_documents: Optional[int] = None
    max_storage_mb: Optional[int] = None
    monthly_query_limit: Optional[int] = None
    monthly_token_limit: Optional[int] = None
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
    quota_alert_threshold: float = 0.8
    # 目前使用量
    current_users: int = 0
    current_documents: int = 0
    current_storage_mb: float = 0.0
    current_monthly_queries: int = 0
    current_monthly_tokens: int = 0
    # 使用率 (0~1)
    users_usage_ratio: Optional[float] = None
    documents_usage_ratio: Optional[float] = None
    storage_usage_ratio: Optional[float] = None
    queries_usage_ratio: Optional[float] = None
    tokens_usage_ratio: Optional[float] = None
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
    quota_alert_threshold: Optional[float] = None
    quota_alert_email: Optional[str] = None


# Plan-based default quotas
PLAN_QUOTAS = {
    "free": {
        "max_users": 5,
        "max_documents": 20,
        "max_storage_mb": 100,
        "monthly_query_limit": 500,
        "monthly_token_limit": 500000,
    },
    "pro": {
        "max_users": 50,
        "max_documents": 200,
        "max_storage_mb": 1000,
        "monthly_query_limit": 5000,
        "monthly_token_limit": 5000000,
    },
    "enterprise": {
        "max_users": None,       # 無限制
        "max_documents": None,
        "max_storage_mb": None,
        "monthly_query_limit": None,
        "monthly_token_limit": None,
    },
}
class TenantInDB(TenantInDBBase):
    pass
