"""
P1-4：職能模組 Router — 單一 DB 路徑（ModuleRegistry），移除記憶體雙軌。

依 AuthorizationContext／職能指派決定可用模組、表單、工具與檢索範圍。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from uuid import UUID

logger = logging.getLogger(__name__)


def authz_role_ids(authz: Any) -> List[str]:
    """從 authz 取角色清單，相容真實 AuthorizationContext（role_ids）與輕量 stub（roles）。

    以 isinstance 檢查而非 getattr 預設值：MagicMock 等 stub 會自動生成任意屬性，
    不能靠「屬性是否存在」判斷；真實 AuthorizationContext 的 role_ids 一定是 list。
    """
    roles = getattr(authz, "role_ids", None)
    if isinstance(roles, (list, tuple)):
        return [str(r) for r in roles]
    roles = getattr(authz, "roles", None)
    if isinstance(roles, (list, tuple)):
        return [str(r) for r in roles]
    return []


def authz_department_ids(authz: Any) -> List[str]:
    """從 authz 取部門清單，相容 AuthorizationContext（department_ids）與 stub（department_id）。"""
    out: List[str] = []
    dept = getattr(authz, "department_id", None)
    if dept is not None and isinstance(dept, (str, UUID)):
        out.append(str(dept))
    depts = getattr(authz, "department_ids", None)
    if isinstance(depts, (list, tuple)):
        for d in depts:
            if str(d) not in out:
                out.append(str(d))
    return out


@dataclass
class ModuleConfig:
    """職能模組設定（統一對外契約）。"""
    name: str
    label: str
    description: str = ""
    forms: List[str] = field(default_factory=list)
    tools: List[str] = field(default_factory=list)
    retrieval_scope: Dict[str, Any] = field(default_factory=dict)
    required_roles: List[str] = field(default_factory=list)
    required_departments: List[str] = field(default_factory=list)
    allowed_job_role_keys: List[str] = field(default_factory=list)
    approver_roles: List[str] = field(default_factory=list)
    intents: List[str] = field(default_factory=list)
    approval_policy: Dict[str, Any] = field(default_factory=dict)
    ux_entrypoints: List[Dict[str, Any]] = field(default_factory=list)


def _from_registry_row(row: Dict[str, Any]) -> ModuleConfig:
    knowledge = row.get("knowledge_scope_policy") or {}
    form_ids = row.get("form_definition_ids") or []
    # form_definition_ids 可能是 UUID 或 form_key 字串
    forms = [str(x) for x in form_ids]
    return ModuleConfig(
        name=row["module_key"],
        label=row.get("name") or row["module_key"],
        description=row.get("description") or "",
        forms=forms,
        tools=list(row.get("allowed_tools") or []),
        retrieval_scope=dict(knowledge),
        required_roles=list(row.get("allowed_roles") or []),
        required_departments=[str(d) for d in (row.get("allowed_departments") or [])],
        allowed_job_role_keys=list(row.get("allowed_job_role_keys") or []),
        intents=list(row.get("supported_intents") or []),
        ux_entrypoints=list(row.get("ux_entrypoints") or []),
    )


class ModuleRouter:
    """DB-backed 職能模組 Router。"""

    def __init__(self, db: Any = None):
        self.db = db
        self._cache: Dict[str, ModuleConfig] = {}
        if db is not None:
            self._load_from_db()

    def _load_from_db(self) -> None:
        from app.services.module_registry import get_module_registry
        from app.services.mka_module_seed import seed_canonical_modules

        registry = get_module_registry(self.db)
        modules = registry.list_modules(include_disabled=False)
        if not modules:
            # 首次：seed 正式五模組後再讀
            seed_canonical_modules(self.db)
            try:
                self.db.commit()
            except Exception:
                self.db.rollback()
            modules = registry.list_modules(include_disabled=False)
        self._cache = {}
        for row in modules:
            cfg = _from_registry_row(row)
            self._cache[cfg.name] = cfg

    def register(self, module: ModuleConfig) -> None:
        self._cache[module.name] = module
        logger.info("Registered module: %s", module.name)

    def get_module(self, name: str) -> Optional[ModuleConfig]:
        return self._cache.get(name)

    def list_modules(self) -> List[str]:
        return sorted(self._cache.keys())

    def get_available_modules(self, authz: Any, job_role_keys: Optional[List[str]] = None) -> List[ModuleConfig]:
        if authz is None:
            return []

        from app.config import settings

        # 若有 DB，以 registry ACL 為準
        if self.db is not None:
            from app.services.module_registry import get_module_registry

            tenant_id = getattr(authz, "tenant_id", None)
            rows = get_module_registry(self.db).get_available_modules(
                tenant_id=tenant_id,
                user_roles=authz_role_ids(authz),
                user_department_ids=authz_department_ids(authz),
                job_role_keys=job_role_keys,
            )
            return [_from_registry_row(r) for r in rows]

        if not settings.MODULE_ROUTER_ENABLED:
            return list(self._cache.values())

        available = []
        user_roles = authz_role_ids(authz)
        user_depts = authz_department_ids(authz)
        for module in self._cache.values():
            if module.required_roles and not any(r in user_roles for r in module.required_roles):
                continue
            if module.required_departments and not any(
                d in module.required_departments for d in user_depts
            ):
                continue
            available.append(module)
        return available

    def get_retrieval_scope(self, module_name: str, authz: Any) -> Dict[str, Any]:
        module = self.get_module(module_name)
        if module is None:
            return {}
        scope = dict(module.retrieval_scope)
        # 正規化：doc_types → 可給 filter 用的鍵
        if "doc_types" in scope and "doc_type" not in scope:
            types = scope.pop("doc_types")
            if isinstance(types, list) and len(types) == 1:
                scope["doc_type"] = types[0]
            elif isinstance(types, list) and types:
                scope["doc_type"] = types  # kb filter 支援 list
        if authz:
            user_depts = authz_department_ids(authz)
            if user_depts and "department" in scope:
                if not any(d in (scope.get("department") or []) for d in user_depts):
                    scope["department"] = user_depts
        return scope

    def get_forms_for_module(self, module_name: str) -> List[str]:
        module = self.get_module(module_name)
        return module.forms if module else []

    def get_tools_for_module(self, module_name: str) -> List[str]:
        module = self.get_module(module_name)
        return module.tools if module else []

    def workspace_entries(self, authz: Any, active_module_keys: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """動態職能工作台入口。"""
        modules = self.get_available_modules(authz)
        if active_module_keys:
            allow = set(active_module_keys)
            modules = [m for m in modules if m.name in allow]
        entries: List[Dict[str, Any]] = []
        for m in modules:
            if m.ux_entrypoints:
                for ep in m.ux_entrypoints:
                    entries.append({
                        "module_key": m.name,
                        "key": ep.get("key"),
                        "label": ep.get("label") or m.label,
                        "path": ep.get("path"),
                        "description": m.description,
                    })
            else:
                for form_key in m.forms:
                    entries.append({
                        "module_key": m.name,
                        "key": form_key,
                        "label": form_key,
                        "path": f"/forms/{form_key}",
                        "description": m.description,
                    })
        return entries


def get_module_router(db: Any = None) -> ModuleRouter:
    """Factory：有 db 時每次從 DB 載入（避免跨請求髒快取）。"""
    if db is not None:
        return ModuleRouter(db=db)
    # 無 DB 時保留輕量單例（僅測試／降級）
    global _router
    if _router is None:
        _router = ModuleRouter(db=None)
    return _router


_router: Optional[ModuleRouter] = None
