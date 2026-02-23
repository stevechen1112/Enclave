"""
Permission checking utilities for role-based access control
with department-scoped and feature-toggle support.
"""
from typing import List, Optional
from uuid import UUID
from fastapi import HTTPException, status, Depends
from sqlalchemy.orm import Session
from app.models.user import User
from app.crud import crud_permission
from app.api import deps


def require_superuser(current_user: User = Depends(deps.get_current_active_user)) -> User:
    """Dependency: require current user to be a superuser."""
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Superuser access required")
    return current_user


class PermissionChecker:
    """
    權限檢查器 — FastAPI Dependency
    使用方式:
        @router.get("/")
        def endpoint(
            db: Session = Depends(deps.get_db),
            current_user: User = Depends(require_admin),
        ):
            ...  # current_user 已通過權限檢查
    """
    
    def __init__(self, allowed_roles: List[str]):
        self.allowed_roles = allowed_roles
    
    def __call__(self, current_user: User = Depends(deps.get_current_active_user)) -> User:
        if current_user.is_superuser:
            return current_user
        if current_user.role not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"此操作需要以下角色之一: {', '.join(self.allowed_roles)}"
            )
        return current_user


# 預定義的權限檢查器
require_owner = PermissionChecker(["owner"])
require_admin = PermissionChecker(["owner", "admin"])
require_hr = PermissionChecker(["owner", "admin", "hr"])
require_employee = PermissionChecker(["owner", "admin", "hr", "employee"])
allow_all_authenticated = PermissionChecker(["owner", "admin", "hr", "employee", "viewer"])


def check_document_permission(user: User, action: str) -> None:
    """
    檢查文件操作權限
    - superuser: 全部權限
    - owner, admin, hr: 可讀寫刪
    - employee: 可讀
    - viewer: 可讀
    """
    if user.is_superuser:
        return
    if action in ["create", "update", "delete"]:
        if user.role not in ["owner", "admin", "hr"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="您沒有權限執行此操作"
            )
    elif action == "read":
        # 所有角色都可以讀取
        pass


def check_audit_permission(user: User) -> None:
    """
    檢查稽核日誌與用量報表權限
    - superuser: 可查看
    - owner, admin, hr: 可查看
    - 其他: 禁止
    """
    if user.is_superuser:
        return
    if user.role not in ["owner", "admin", "hr"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="您沒有權限查看稽核日誌或用量報表"
        )


def check_user_management_permission(user: User) -> None:
    """
    檢查使用者管理權限
    - superuser: 可管理
    - owner, admin: 可管理
    - 其他: 禁止
    """
    if user.is_superuser:
        return
    if user.role not in ["owner", "admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="您沒有權限管理使用者"
        )


def check_department_permission(user: User) -> None:
    """
    檢查部門管理權限
    - superuser / owner / admin: 可管理
    - hr: 可讀取
    - 其他: 禁止
    """
    if user.is_superuser:
        return
    if user.role not in ["owner", "admin", "hr"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="您沒有權限管理部門"
        )


def check_feature_enabled(db: Session, user: User, feature: str) -> None:
    """
    檢查功能模組是否已啟用
    - superuser: bypass
    - 根據 FeaturePermission 表判斷
    """
    if user.is_superuser:
        return
    allowed = crud_permission.is_feature_allowed(
        db, tenant_id=user.tenant_id, feature=feature, role=user.role
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"此功能模組 [{feature}] 未對您的角色開啓"
        )


def can_access_document_by_department(user: User, document_department_id: Optional[UUID]) -> bool:
    """
    部門級文件存取判斷
    - superuser / owner / admin: 可存取所有部門文件
    - hr: 可存取所有部門文件
    - employee / viewer: 只能存取自己部門的文件 或 無部門限制的文件
    """
    if user.is_superuser or user.role in ["owner", "admin", "hr"]:
        return True
    # 文件未指定部門 → 全員可見
    if document_department_id is None:
        return True
    # 使用者未指定部門 → 只能看無部門限制的文件
    if user.department_id is None:
        return False
    return user.department_id == document_department_id
