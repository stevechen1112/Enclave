from typing import Optional, List
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, ConfigDict


# ─── Department Schemas ───

class DepartmentBase(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    parent_id: Optional[UUID] = None


class DepartmentCreate(DepartmentBase):
    name: str


class DepartmentUpdate(DepartmentBase):
    is_active: Optional[bool] = None


class Department(DepartmentBase):
    id: UUID
    tenant_id: UUID
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class DepartmentTree(Department):
    """含子部門的樹狀結構"""
    children: List["DepartmentTree"] = []


# ─── Feature Permission Schemas ───

class FeaturePermissionBase(BaseModel):
    feature: str
    role: Optional[str] = None
    allowed: bool = True
    config: Optional[dict] = None


class FeaturePermissionCreate(FeaturePermissionBase):
    pass


class FeaturePermissionUpdate(BaseModel):
    allowed: Optional[bool] = None
    config: Optional[dict] = None


class FeaturePermission(FeaturePermissionBase):
    id: UUID
    tenant_id: UUID
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# 可用功能模組列表
AVAILABLE_FEATURES = [
    "chat",
    "documents",
    "audit",
    "kb",
    "user_mgmt",
    "departments",
]


# Resolve circular reference for tree
DepartmentTree.model_rebuild()
