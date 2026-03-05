"""
Admin response schemas — 管理後台 API（P9-1/P9-2）。

Extracted from ``app/api/v1/endpoints/admin.py`` to keep endpoint
modules free of inline Pydantic class definitions.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class OrgDashboard(BaseModel):
    """Single-org dashboard — replaces the original SaaS PlatformDashboard."""

    org_name: str
    total_users: int
    active_users: int
    total_documents: int
    total_conversations: int
    total_actions: int
    total_cost: float
    daily_actions: List[Dict[str, Any]]
    top_users: List[Dict[str, Any]]


class AdminUserInfo(BaseModel):
    """Serialised user record returned by the admin user-list endpoint."""

    id: str
    email: str
    full_name: Optional[str] = None
    role: Optional[str] = None
    status: Optional[str] = None
    tenant_id: str
    department_name: Optional[str] = None
    created_at: Optional[datetime] = None


class SystemHealth(BaseModel):
    """Current system health snapshot returned by the health endpoint."""

    status: str
    database: str
    redis: str
    uptime_seconds: float
    python_version: str
    active_connections: int
