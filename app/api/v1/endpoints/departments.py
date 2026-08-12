"""
部門管理 + 功能權限管理 API
"""
from typing import Any, List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api import deps
from app.api.deps_permissions import (
    check_department_permission,
    check_user_management_permission,
    check_feature_enabled,
)
from app.crud import crud_permission
from app.models.user import User
from app.schemas.permission import (
    Department,
    DepartmentCreate,
    DepartmentUpdate,
    DepartmentTree,
    FeaturePermission,
    FeaturePermissionCreate,
    AVAILABLE_FEATURES,
)

router = APIRouter()


# ═══════════════════════════════════════════
#  部門 CRUD 端點
# ═══════════════════════════════════════════

@router.get("/options")
def list_department_options(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> List[dict[str, str]]:
    """供租戶內文件篩選使用的最小唯讀部門清單。

    部門管理 API 維持 governance 權限；一般知識瀏覽者只會取得目前
    租戶的啟用部門 id 與名稱，不會取得權限設定或管理能力。
    """
    departments = crud_permission.get_departments_by_tenant(
        db, tenant_id=current_user.tenant_id, include_inactive=False
    )
    return [{"id": str(department.id), "name": department.name} for department in departments]


@router.get("/", response_model=List[Department])
def list_departments(
    include_inactive: bool = False,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """列出本租戶所有部門"""
    check_department_permission(current_user)
    return crud_permission.get_departments_by_tenant(
        db, tenant_id=current_user.tenant_id, include_inactive=include_inactive
    )


@router.get("/tree", response_model=List[DepartmentTree])
def department_tree(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """取得部門樹狀結構"""
    check_department_permission(current_user)
    all_depts = crud_permission.get_departments_by_tenant(
        db, tenant_id=current_user.tenant_id
    )

    # Build tree
    dept_map = {d.id: DepartmentTree.model_validate(d) for d in all_depts}
    roots: list[DepartmentTree] = []
    for d in dept_map.values():
        if d.parent_id and d.parent_id in dept_map:
            dept_map[d.parent_id].children.append(d)
        else:
            roots.append(d)
    return roots


@router.post("/", response_model=Department, status_code=status.HTTP_201_CREATED)
def create_department(
    dept_in: DepartmentCreate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """建立部門"""
    check_department_permission(current_user)
    if current_user.role not in ["owner", "admin"] and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="只有 owner/admin 可建立部門")
    return crud_permission.create_department(
        db, tenant_id=current_user.tenant_id, obj_in=dept_in
    )


@router.get("/{department_id}", response_model=Department)
def get_department(
    department_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """取得單一部門"""
    check_department_permission(current_user)
    dept = crud_permission.get_department(db, department_id=department_id)
    if not dept or dept.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="部門不存在")
    return dept


@router.put("/{department_id}", response_model=Department)
def update_department(
    department_id: UUID,
    dept_in: DepartmentUpdate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """更新部門"""
    check_department_permission(current_user)
    if current_user.role not in ["owner", "admin"] and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="只有 owner/admin 可修改部門")
    dept = crud_permission.get_department(db, department_id=department_id)
    if not dept or dept.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="部門不存在")
    updated = crud_permission.update_department(db, department_id=department_id, obj_in=dept_in)
    return updated


@router.delete("/{department_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_department(
    department_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> None:
    """停用部門 (軟刪除)"""
    check_department_permission(current_user)
    if current_user.role not in ["owner", "admin"] and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="只有 owner/admin 可停用部門")
    dept = crud_permission.get_department(db, department_id=department_id)
    if not dept or dept.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="部門不存在")
    crud_permission.delete_department(db, department_id=department_id)


# ═══════════════════════════════════════════
#  功能權限端點
# ═══════════════════════════════════════════

@router.get("/features/available")
def list_available_features(
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """列出所有可用的功能模組名稱"""
    return {"features": AVAILABLE_FEATURES}


@router.get("/features/", response_model=List[FeaturePermission])
def list_feature_permissions(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """列出本租戶所有功能權限設定"""
    check_user_management_permission(current_user)
    return crud_permission.get_feature_permissions(db, tenant_id=current_user.tenant_id)


@router.post("/features/", response_model=FeaturePermission)
def set_feature_permission(
    perm_in: FeaturePermissionCreate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """設定功能權限 (upsert)"""
    check_user_management_permission(current_user)
    if perm_in.feature not in AVAILABLE_FEATURES:
        raise HTTPException(
            status_code=400,
            detail=f"未知功能模組: {perm_in.feature}。可用: {AVAILABLE_FEATURES}"
        )
    return crud_permission.set_feature_permission(
        db, tenant_id=current_user.tenant_id, obj_in=perm_in
    )
