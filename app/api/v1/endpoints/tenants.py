from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api import deps
from app.api.deps_permissions import require_superuser
from app.crud import crud_tenant
from app.models.user import User
from app.schemas.tenant import Tenant, TenantUpdate

router = APIRouter()

# P9-1: Removed GET / (list all tenants) and POST / (create tenant)
#        On-premise is single-org only. Admins read/update the single org record.


@router.get("/me", response_model=Tenant)
def read_my_org(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """取得目前登入者所屬組織的資訊"""
    org = crud_tenant.get(db, tenant_id=current_user.tenant_id)
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return org


@router.get("/{tenant_id}", response_model=Tenant)
def read_tenant(
    *,
    db: Session = Depends(deps.get_db),
    tenant_id: UUID,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """組織詳情（僅限查看自己的組織）"""
    tenant = crud_tenant.get(db, tenant_id=tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found"
        )
    if tenant.id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )
    return tenant


@router.put("/{tenant_id}", response_model=Tenant)
def update_tenant(
    *,
    db: Session = Depends(deps.get_db),
    tenant_id: UUID,
    tenant_in: TenantUpdate,
    current_user: User = Depends(require_superuser),
) -> Any:
    """更新組織名稱 / 描述（僅限 superuser）"""
    tenant = crud_tenant.get(db, tenant_id=tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found"
        )
    tenant = crud_tenant.update(db, db_obj=tenant, obj_in=tenant_in)
    return tenant
