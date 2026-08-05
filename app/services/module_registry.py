"""
MKA Module Registry — DB-backed 職能模組註冊表。

對照 ENGINEERING_PLAN.md §4.1、§5.4：
- 從 DB 讀取 JobModule + TenantModuleBinding
- 回傳使用者可用的模組
- 支援 admin enable/disable
- 與記憶體 module_router.py 互補（router 做路由，registry 做持久化）
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class ModuleRegistry:
    """DB-backed 職能模組註冊表。"""

    def __init__(self, db: Session):
        self.db = db

    def list_modules(
        self,
        tenant_id: Optional[UUID] = None,
        include_disabled: bool = False,
    ) -> List[Dict[str, Any]]:
        """列出模組（含全租戶 + 租戶專屬）。"""
        from app.models.mka import JobModule

        query = self.db.query(JobModule)
        if not include_disabled:
            query = query.filter(JobModule.status.in_(["enabled", "draft"]))

        # 全租戶（tenant_id=NULL）+ 指定租戶
        if tenant_id:
            from sqlalchemy import or_
            query = query.filter(
                or_(JobModule.tenant_id.is_(None), JobModule.tenant_id == tenant_id)
            )
        else:
            query = query.filter(JobModule.tenant_id.is_(None))

        modules = query.all()
        return [self._to_dict(m) for m in modules]

    def get_module(self, module_key: str, tenant_id: Optional[UUID] = None) -> Optional[Dict[str, Any]]:
        """取得單一模組。"""
        from app.models.mka import JobModule
        from sqlalchemy import or_

        query = self.db.query(JobModule).filter(JobModule.module_key == module_key)
        if tenant_id:
            query = query.filter(
                or_(JobModule.tenant_id.is_(None), JobModule.tenant_id == tenant_id)
            )
        else:
            query = query.filter(JobModule.tenant_id.is_(None))

        module = query.first()
        return self._to_dict(module) if module else None

    def get_available_modules(
        self,
        tenant_id: UUID,
        user_roles: List[str],
        user_department_ids: List[str],
    ) -> List[Dict[str, Any]]:
        """取得使用者可用的模組（含 tenant binding 檢查）。"""
        from app.models.mka import JobModule, TenantModuleBinding
        from sqlalchemy import or_

        # 1. 取得所有 enabled 模組
        query = self.db.query(JobModule).filter(JobModule.status == "enabled")
        query = query.filter(
            or_(JobModule.tenant_id.is_(None), JobModule.tenant_id == tenant_id)
        )
        all_modules = query.all()

        # 2. 檢查 tenant binding
        bindings = (
            self.db.query(TenantModuleBinding)
            .filter(
                TenantModuleBinding.tenant_id == tenant_id,
                TenantModuleBinding.enabled.is_(True),
            )
            .all()
        )
        bound_keys = {b.module_key for b in bindings}

        available = []
        for module in all_modules:
            # 若有 tenant binding 限制，檢查是否已啟用
            if bound_keys and module.module_key not in bound_keys:
                # 檢查是否為全租戶模組（tenant_id=NULL）
                if module.tenant_id is not None:
                    continue

            # 檢查角色
            if module.allowed_roles:
                if not any(r in user_roles for r in module.allowed_roles):
                    continue

            # 檢查部門
            if module.allowed_departments:
                if not any(str(d) in module.allowed_departments for d in user_department_ids):
                    continue

            available.append(self._to_dict(module))

        return available

    def enable_module(
        self,
        tenant_id: UUID,
        module_key: str,
        config: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """啟用租戶模組。"""
        from app.models.mka import TenantModuleBinding

        existing = (
            self.db.query(TenantModuleBinding)
            .filter(
                TenantModuleBinding.tenant_id == tenant_id,
                TenantModuleBinding.module_key == module_key,
            )
            .first()
        )

        if existing:
            existing.enabled = True
            if config:
                existing.config_json = config
        else:
            binding = TenantModuleBinding(
                tenant_id=tenant_id,
                module_key=module_key,
                enabled=True,
                license_state="trial",
                config_json=config or {},
            )
            self.db.add(binding)

        self.db.commit()
        logger.info(f"Module {module_key} enabled for tenant {tenant_id}")
        return True

    def disable_module(self, tenant_id: UUID, module_key: str) -> bool:
        """停用租戶模組。"""
        from app.models.mka import TenantModuleBinding

        binding = (
            self.db.query(TenantModuleBinding)
            .filter(
                TenantModuleBinding.tenant_id == tenant_id,
                TenantModuleBinding.module_key == module_key,
            )
            .first()
        )

        if binding:
            binding.enabled = False
            self.db.commit()
            logger.info(f"Module {module_key} disabled for tenant {tenant_id}")
            return True
        return False

    def get_interaction_capabilities(self, tenant_id: UUID) -> Dict[str, bool]:
        """取得租戶的 interaction capabilities（誠實狀態）。"""
        from app.config import settings

        return {
            "voice": settings.VOICE_STT_ENABLED,
            "camera": False,  # 待前端 PWA 實作
            "qr": False,  # 待 scene resolver 實作
            "offline": False,  # 待 PWA service worker 實作
        }

    def _to_dict(self, module: Any) -> Dict[str, Any]:
        return {
            "id": str(module.id),
            "module_key": module.module_key,
            "tenant_id": str(module.tenant_id) if module.tenant_id else None,
            "name": module.name,
            "description": module.description,
            "version": module.version,
            "status": module.status,
            "allowed_roles": module.allowed_roles or [],
            "allowed_departments": module.allowed_departments or [],
            "knowledge_scope_policy": module.knowledge_scope_policy or {},
            "supported_intents": module.supported_intents or [],
            "allowed_tools": module.allowed_tools or [],
            "form_definition_ids": module.form_definition_ids or [],
            "ux_entrypoints": module.ux_entrypoints or [],
            "metrics_config": module.metrics_config or {},
        }


def get_module_registry(db: Session) -> ModuleRegistry:
    """工廠函式。"""
    return ModuleRegistry(db)