"""MKA Module Admin API — job module registration, tenant binding, compatibility matrix.

§5.4 Module API:
  GET  /job-modules
  GET  /job-modules/{key}
  POST /admin/job-modules/{key}/enable
  PATCH /admin/job-modules/{key}/config
  DELETE /admin/job-modules/{key}/disable
  GET  /admin/job-modules/compatibility
"""
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api import deps
from app.api.deps_permissions import allow_all_authenticated, require_admin
from app.models.user import User
from app.services.module_admin import ModuleAdminService, CompatibilityMatrix
from app.services.module_registry import get_module_registry

router = APIRouter(prefix="/job-modules", tags=["job-modules"])


class ModuleEnableRequest(BaseModel):
    config: Optional[Dict[str, Any]] = None
    enabled_packs: Optional[List[str]] = None


class ModuleConfigRequest(BaseModel):
    config: Dict[str, Any]


# ── Public endpoints ──

@router.get("")
def list_modules(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(allow_all_authenticated),
):
    """List all job modules available to the current tenant."""
    registry = get_module_registry(db)
    modules = registry.list_modules(tenant_id=current_user.tenant_id)
    return {"modules": modules, "count": len(modules)}


# ── Admin endpoints (registered BEFORE /{module_key} to avoid route shadowing) ──

@router.post("/admin/{module_key}/enable")
def enable_module(
    module_key: str,
    request: ModuleEnableRequest = ModuleEnableRequest(),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_admin),
):
    """Enable a job module for the current tenant (admin only)."""
    admin = ModuleAdminService(db)
    result = admin.enable_for_tenant(
        tenant_id=current_user.tenant_id,
        module_key=module_key,
        config=request.config,
        enabled_packs=request.enabled_packs,
    )
    if not result.get("enabled"):
        raise HTTPException(
            status_code=400,
            detail=result.get("reason", "module enable failed"),
        )
    return result


@router.delete("/admin/{module_key}/disable")
def disable_module(
    module_key: str,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_admin),
):
    """Disable a job module for the current tenant (admin only)."""
    admin = ModuleAdminService(db)
    result = admin.disable_for_tenant(
        tenant_id=current_user.tenant_id,
        module_key=module_key,
    )
    return result


@router.patch("/admin/{module_key}/config")
def update_module_config(
    module_key: str,
    request: ModuleConfigRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_admin),
):
    """Update a job module's tenant configuration (admin only)."""
    registry = get_module_registry(db)
    success = registry.update_config(
        tenant_id=current_user.tenant_id,
        module_key=module_key,
        config=request.config,
    )
    if not success:
        raise HTTPException(status_code=404, detail=f"module not found: {module_key}")
    return {"module_key": module_key, "updated": True}


@router.get("/admin/compatibility")
def list_compatibility(
    current_user: User = Depends(require_admin),
):
    """List the module compatibility matrix (admin only)."""
    matrix = CompatibilityMatrix()
    return {"entries": matrix.list_entries()}


@router.post("/admin/register")
def register_module(
    module_key: str = Query(...),
    name: str = Query(...),
    description: str = Query(""),
    allowed_roles: Optional[str] = Query(None),
    allowed_departments: Optional[str] = Query(None),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_admin),
):
    """Register a new job module (admin only, global)."""
    admin = ModuleAdminService(db)
    result = admin.register_module(
        module_key=module_key,
        name=name,
        description=description,
        allowed_roles=allowed_roles.split(",") if allowed_roles else None,
        allowed_departments=allowed_departments.split(",") if allowed_departments else None,
    )
    return result


# ── Public endpoint: get by key (registered AFTER admin routes) ──

@router.get("/{module_key}")
def get_module(
    module_key: str,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(allow_all_authenticated),
):
    """Get a specific job module by key."""
    registry = get_module_registry(db)
    module = registry.get_module(module_key, tenant_id=current_user.tenant_id)
    if module is None:
        raise HTTPException(status_code=404, detail=f"module not found: {module_key}")
    return module
