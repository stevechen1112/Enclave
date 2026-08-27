"""Job role assignment API — manufacturing job functions (not security roles)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api import deps
from app.models.mka import JobRole, UserJobRoleAssignment
from app.models.user import User
from app.services.mka_module_seed import (
    ensure_tenant_module_bindings,
    seed_canonical_modules,
    seed_canonical_task_definitions,
    seed_default_job_roles,
)

router = APIRouter()


class JobRoleCreate(BaseModel):
    role_key: str = Field(..., min_length=1, max_length=64)
    name: str
    description: Optional[str] = None
    department_ids: List[str] = Field(default_factory=list)
    default_module_keys: List[str] = Field(default_factory=list)
    active: bool = True


class AssignmentCreate(BaseModel):
    user_id: UUID
    job_role_id: UUID
    department_id: Optional[UUID] = None
    is_primary: bool = False


def _require_admin(user: User) -> None:
    if not (user.is_superuser or user.role in {"owner", "admin"}):
        raise HTTPException(status_code=403, detail="admin required")


def _role_dict(row: JobRole) -> Dict[str, Any]:
    return {
        "id": str(row.id),
        "tenant_id": str(row.tenant_id),
        "role_key": row.role_key,
        "name": row.name,
        "description": row.description,
        "department_ids": row.department_ids or [],
        "default_module_keys": row.default_module_keys or [],
        "active": row.active,
    }


def _assign_dict(row: UserJobRoleAssignment, role: Optional[JobRole] = None) -> Dict[str, Any]:
    return {
        "id": str(row.id),
        "user_id": str(row.user_id),
        "job_role_id": str(row.job_role_id),
        "department_id": str(row.department_id) if row.department_id else None,
        "is_primary": row.is_primary,
        "active": row.active,
        "role": _role_dict(role) if role else None,
    }


@router.post("/job-roles/seed")
def seed_roles_and_modules(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
) -> Dict[str, Any]:
    _require_admin(current_user)
    modules = seed_canonical_modules(db)
    bindings = ensure_tenant_module_bindings(db, current_user.tenant_id)
    roles = seed_default_job_roles(db, current_user.tenant_id)
    tasks = seed_canonical_task_definitions(db)
    db.commit()
    return {
        "modules_upserted": modules,
        "bindings_created": bindings,
        "roles_upserted": roles,
        "task_definitions_upserted": tasks,
    }


@router.get("/job-roles")
def list_job_roles(
    include_inactive: bool = False,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
) -> List[Dict[str, Any]]:
    query = db.query(JobRole).filter(JobRole.tenant_id == current_user.tenant_id)
    if not include_inactive:
        query = query.filter(JobRole.active.is_(True))
    elif not (current_user.is_superuser or current_user.role in {"owner", "admin"}):
        raise HTTPException(status_code=403, detail="admin required")
    return [_role_dict(r) for r in query.all()]


class JobRoleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    department_ids: Optional[List[str]] = None
    default_module_keys: Optional[List[str]] = None
    active: Optional[bool] = None


@router.patch("/job-roles/{role_id}")
def update_job_role(
    role_id: UUID,
    body: JobRoleUpdate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
) -> Dict[str, Any]:
    _require_admin(current_user)
    row = (
        db.query(JobRole)
        .filter(JobRole.id == role_id, JobRole.tenant_id == current_user.tenant_id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="job role not found")
    for key, value in body.model_dump(exclude_none=True).items():
        setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return _role_dict(row)


@router.post("/job-roles")
def create_job_role(
    body: JobRoleCreate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
) -> Dict[str, Any]:
    _require_admin(current_user)
    exists = (
        db.query(JobRole)
        .filter(
            JobRole.tenant_id == current_user.tenant_id,
            JobRole.role_key == body.role_key,
        )
        .first()
    )
    if exists:
        raise HTTPException(status_code=409, detail="role_key exists")
    row = JobRole(tenant_id=current_user.tenant_id, **body.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return _role_dict(row)


@router.get("/job-roles/me")
def my_job_roles(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
) -> Dict[str, Any]:
    from app.services.job_context import build_effective_job_context

    ctx = build_effective_job_context(db, current_user)
    return {
        "assignments": [a.to_dict() for a in ctx.assignments],
        "active_job_role": ctx.active_job_role.to_dict() if ctx.active_job_role else None,
        "needs_job_role_assignment": ctx.needs_job_role_assignment,
    }


class ActiveJobRoleSwitch(BaseModel):
    job_role_id: UUID


class ModuleConfigUpdate(BaseModel):
    config: Dict[str, Any] = Field(default_factory=dict)


class ModuleBindingUpdate(BaseModel):
    enabled: bool


@router.put("/job-modules/{module_key}/binding")
def set_module_binding(
    module_key: str,
    body: ModuleBindingUpdate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
) -> Dict[str, Any]:
    """租戶 opt-in 啟用／停用模組。"""
    _require_admin(current_user)
    from app.models.mka import TenantModuleBinding
    from app.services.module_registry import get_module_registry

    registry = get_module_registry(db)
    if registry.get_module(module_key, tenant_id=None) is None:
        raise HTTPException(status_code=404, detail="module not found")
    binding = (
        db.query(TenantModuleBinding)
        .filter(
            TenantModuleBinding.tenant_id == current_user.tenant_id,
            TenantModuleBinding.module_key == module_key,
        )
        .first()
    )
    if binding is None:
        binding = TenantModuleBinding(
            tenant_id=current_user.tenant_id,
            module_key=module_key,
            enabled=False,
            license_state="trial",
            config_json={},
            config_version=0,
        )
        db.add(binding)
    binding.enabled = body.enabled
    db.commit()
    return {
        "module_key": module_key,
        "enabled": binding.enabled,
        "config_version": binding.config_version,
    }


@router.get("/job-modules/{module_key}/effective-config")
def preview_effective_config(
    module_key: str,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
) -> Dict[str, Any]:
    """租戶模組 effective config 預覽（defaults ← overrides，含版本號）。"""
    _require_admin(current_user)
    from app.services.module_registry import get_module_registry

    return get_module_registry(db).get_effective_config(current_user.tenant_id, module_key)


@router.put("/job-modules/{module_key}/config")
def update_module_config(
    module_key: str,
    body: ModuleConfigUpdate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
) -> Dict[str, Any]:
    """版本化更新租戶模組 config；schema 驗證失敗回 422。"""
    _require_admin(current_user)
    from app.services.module_registry import get_module_registry

    try:
        return get_module_registry(db).update_config_versioned(
            current_user.tenant_id, module_key, body.config
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/job-roles/active")
def switch_active_job_role(
    body: ActiveJobRoleSwitch,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
) -> Dict[str, Any]:
    """切換 active 職能（持久化到 users.active_job_role_id）。

    必須是本人的有效指派；切換後前端應重新取得 bootstrap。
    """
    from app.services.job_context import set_active_job_role

    try:
        target = set_active_job_role(db, current_user, body.job_role_id)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    db.commit()
    return {"active_job_role": target.to_dict()}


@router.get("/job-roles/assignments")
def list_assignments(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
) -> List[Dict[str, Any]]:
    _require_admin(current_user)
    rows = (
        db.query(UserJobRoleAssignment)
        .filter(UserJobRoleAssignment.tenant_id == current_user.tenant_id)
        .all()
    )
    role_ids = {a.job_role_id for a in rows}
    roles = (
        {r.id: r for r in db.query(JobRole).filter(JobRole.id.in_(role_ids)).all()}
        if role_ids
        else {}
    )
    return [_assign_dict(a, roles.get(a.job_role_id)) for a in rows]


@router.post("/job-roles/assignments")
def assign_job_role(
    body: AssignmentCreate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
) -> Dict[str, Any]:
    _require_admin(current_user)
    role = (
        db.query(JobRole)
        .filter(
            JobRole.id == body.job_role_id,
            JobRole.tenant_id == current_user.tenant_id,
        )
        .first()
    )
    if role is None:
        raise HTTPException(status_code=404, detail="job role not found")
    existing = (
        db.query(UserJobRoleAssignment)
        .filter(
            UserJobRoleAssignment.tenant_id == current_user.tenant_id,
            UserJobRoleAssignment.user_id == body.user_id,
            UserJobRoleAssignment.job_role_id == body.job_role_id,
        )
        .first()
    )
    if existing:
        existing.active = True
        existing.is_primary = body.is_primary
        existing.department_id = body.department_id
        row = existing
    else:
        row = UserJobRoleAssignment(
            tenant_id=current_user.tenant_id,
            user_id=body.user_id,
            job_role_id=body.job_role_id,
            department_id=body.department_id,
            is_primary=body.is_primary,
            active=True,
        )
        db.add(row)
    if body.is_primary:
        others = (
            db.query(UserJobRoleAssignment)
            .filter(
                UserJobRoleAssignment.tenant_id == current_user.tenant_id,
                UserJobRoleAssignment.user_id == body.user_id,
                UserJobRoleAssignment.job_role_id != body.job_role_id,
            )
            .all()
        )
        for other in others:
            other.is_primary = False
    db.commit()
    db.refresh(row)
    return _assign_dict(row, role)


@router.delete("/job-roles/assignments/{assignment_id}")
def deactivate_assignment(
    assignment_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
) -> Dict[str, Any]:
    _require_admin(current_user)
    row = (
        db.query(UserJobRoleAssignment)
        .filter(
            UserJobRoleAssignment.id == assignment_id,
            UserJobRoleAssignment.tenant_id == current_user.tenant_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="assignment not found")
    row.active = False
    db.commit()
    return {"id": str(row.id), "active": False}
