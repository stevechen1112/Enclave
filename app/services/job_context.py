"""EffectiveJobContext — 職能任務平台的單一 runtime 上下文（Phase 1）。

安全角色（User.role → AuthorizationContext）與業務職能（JobRole 指派）分離：
- 安全角色決定系統權限（capability）。
- 職能指派決定可使用哪些模組／任務。
- 模組存取必須同時通過：安全角色 ACL、租戶 binding、職能 allowlist。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass
class JobRoleInfo:
    assignment_id: str
    job_role_id: str
    role_key: Optional[str]
    name: Optional[str]
    is_primary: bool
    default_module_keys: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.assignment_id,
            "job_role_id": self.job_role_id,
            "is_primary": self.is_primary,
            "role_key": self.role_key,
            "name": self.name,
            "default_module_keys": list(self.default_module_keys),
        }


@dataclass
class EffectiveJobContext:
    tenant_id: UUID
    user_id: UUID
    security_roles: List[str]
    department_ids: List[str]
    is_superuser: bool
    assignments: List[JobRoleInfo] = field(default_factory=list)
    active_job_role: Optional[JobRoleInfo] = None
    scene: Optional[Dict[str, Any]] = None

    @property
    def needs_job_role_assignment(self) -> bool:
        """無任何有效職能指派 — 工作台必須顯示空態，禁止回退全部功能。"""
        return not self.assignments

    @property
    def active_module_keys(self) -> List[str]:
        """active 職能宣告的模組；無職能時為空（不是全部）。"""
        if self.active_job_role is None:
            return []
        return list(self.active_job_role.default_module_keys)

    @property
    def active_job_role_keys(self) -> List[str]:
        if self.active_job_role is None or not self.active_job_role.role_key:
            return []
        return [self.active_job_role.role_key]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tenant_id": str(self.tenant_id),
            "user_id": str(self.user_id),
            "security_roles": list(self.security_roles),
            "department_ids": list(self.department_ids),
            "job_role_assignments": [a.to_dict() for a in self.assignments],
            "active_job_role": self.active_job_role.to_dict() if self.active_job_role else None,
            "needs_job_role_assignment": self.needs_job_role_assignment,
            "active_module_keys": self.active_module_keys,
            "scene": self.scene,
        }


def build_effective_job_context(
    db: Session,
    user: Any,
    scene: Optional[Dict[str, Any]] = None,
) -> EffectiveJobContext:
    """從 User 建立 EffectiveJobContext（含 active 職能解析）。

    active 職能解析順序：users.active_job_role_id（持久化選擇）
    → is_primary 指派 → 第一個 active 指派。
    """
    from app.core.authorization import AuthorizationContext
    from app.models.mka import JobRole, UserJobRoleAssignment

    authz = AuthorizationContext.from_user(user)

    rows = (
        db.query(UserJobRoleAssignment)
        .filter(
            UserJobRoleAssignment.tenant_id == user.tenant_id,
            UserJobRoleAssignment.user_id == user.id,
            UserJobRoleAssignment.active.is_(True),
        )
        .all()
    )
    role_map = {
        r.id: r
        for r in db.query(JobRole)
        .filter(JobRole.tenant_id == user.tenant_id, JobRole.active.is_(True))
        .all()
    }

    assignments: List[JobRoleInfo] = []
    for a in rows:
        role = role_map.get(a.job_role_id)
        if role is None:
            continue  # 職能已停用 → 指派視為無效
        assignments.append(JobRoleInfo(
            assignment_id=str(a.id),
            job_role_id=str(a.job_role_id),
            role_key=role.role_key,
            name=role.name,
            is_primary=bool(a.is_primary),
            default_module_keys=list(role.default_module_keys or []),
        ))

    active: Optional[JobRoleInfo] = None
    persisted_id = getattr(user, "active_job_role_id", None)
    if persisted_id:
        active = next(
            (a for a in assignments if a.job_role_id == str(persisted_id)), None
        )
    if active is None:
        active = next((a for a in assignments if a.is_primary), None)
    if active is None and assignments:
        active = assignments[0]

    return EffectiveJobContext(
        tenant_id=user.tenant_id,
        user_id=user.id,
        security_roles=list(authz.role_ids),
        department_ids=[str(d) for d in authz.department_ids],
        is_superuser=bool(getattr(user, "is_superuser", False)),
        assignments=assignments,
        active_job_role=active,
        scene=scene,
    )


def set_active_job_role(db: Session, user: Any, job_role_id: UUID) -> JobRoleInfo:
    """持久化使用者的 active 職能；必須是有效指派，否則 fail-closed。"""
    ctx = build_effective_job_context(db, user)
    target = next((a for a in ctx.assignments if a.job_role_id == str(job_role_id)), None)
    if target is None:
        raise ValueError("此職能未指派給目前使用者或已停用")
    user.active_job_role_id = UUID(target.job_role_id)
    db.flush()
    return target


class ModuleAccessDenied(PermissionError):
    """模組對目前 EffectiveJobContext 不可用（安全角色／binding／職能任一不通過）。"""


def assert_module_access(db: Session, user: Any, module_key: str) -> Dict[str, Any]:
    """直接 URL／明確指定模組時的授權檢查（不只隱藏選單）。

    通過時回傳模組 dict；否則 raise ModuleAccessDenied。
    """
    from app.services.module_registry import get_module_registry

    ctx = build_effective_job_context(db, user)
    registry = get_module_registry(db)
    module = registry.get_module(module_key, tenant_id=user.tenant_id)
    if module is None or module.get("status") != "enabled":
        raise ModuleAccessDenied(f"模組不存在或未啟用：{module_key}")

    available = registry.get_available_modules(
        tenant_id=user.tenant_id,
        user_roles=list(ctx.security_roles),
        user_department_ids=list(ctx.department_ids),
        job_role_keys=list(ctx.active_job_role_keys),
    )
    if not any(m["module_key"] == module_key for m in available):
        raise ModuleAccessDenied(f"目前職能／角色無權使用模組：{module_key}")
    return module


def assert_form_access(db: Session, user: Any, form_key: str) -> None:
    """表單直接 URL 授權：表單所屬模組必須對目前 EffectiveJobContext 可用。

    無模組認領的表單（未掛進任何 JobModule）維持開放，避免阻斷舊資料。
    """
    from app.services.module_registry import get_module_registry

    registry = get_module_registry(db)
    claiming = [
        m for m in registry.list_modules(tenant_id=user.tenant_id)
        if form_key in [str(f) for f in (m.get("form_definition_ids") or [])]
    ]
    if not claiming:
        return
    ctx = build_effective_job_context(db, user)
    available = registry.get_available_modules(
        tenant_id=user.tenant_id,
        user_roles=list(ctx.security_roles),
        user_department_ids=list(ctx.department_ids),
        job_role_keys=list(ctx.active_job_role_keys),
    )
    available_keys = {m["module_key"] for m in available}
    if not any(m["module_key"] in available_keys for m in claiming):
        raise ModuleAccessDenied(f"目前職能／角色無權使用表單：{form_key}")


def module_allowed_for_context(module: Dict[str, Any], ctx: EffectiveJobContext) -> bool:
    """模組是否對此上下文可用：安全角色 + 部門 + 職能 allowlist 三者皆過。

    注意：租戶 binding 由 ModuleRegistry.get_available_modules 把關，
    此函式處理的是「已 bound 模組」的使用者層 ACL。
    """
    allowed_roles = module.get("allowed_roles") or []
    if allowed_roles and not any(r in ctx.security_roles for r in allowed_roles):
        return False
    allowed_depts = [str(d) for d in (module.get("allowed_departments") or [])]
    if allowed_depts and not any(d in allowed_depts for d in ctx.department_ids):
        return False
    allowed_job_keys = module.get("allowed_job_role_keys") or []
    if allowed_job_keys:
        # 模組限定職能：必須以「被允許的職能」身分執行；superuser 不豁免業務職能
        if not any(k in allowed_job_keys for k in ctx.active_job_role_keys):
            return False
    return True
