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
        from app.platform.knowledge import query_mode_keys

        query = self.db.query(JobModule).filter(
            JobModule.module_key.notin_(query_mode_keys())
        )
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
        from app.platform.knowledge import is_core_query_mode

        if is_core_query_mode(module_key):
            return None
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
        job_role_keys: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """取得使用者可用的模組（含 tenant binding 檢查）。

        job_role_keys：呼叫者的 active 業務職能 key 清單。
        - None：不套用職能過濾（管理／設定介面用途）。
        - []（空清單）：無職能指派 → 只回傳「不限職能」的模組。
        - ["sales", ...]：模組有 allowed_job_role_keys 時需交集。
        """
        from app.models.mka import JobModule, TenantModuleBinding
        from app.platform.knowledge import query_mode_keys
        from sqlalchemy import or_

        # 1. 取得所有 enabled 模組
        query = self.db.query(JobModule).filter(
            JobModule.status == "enabled",
            JobModule.module_key.notin_(query_mode_keys()),
        )
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

        # 新租戶 opt-in：無任何啟用 binding 的租戶看不到全域模組。
        # 合成 Demo 的 binding 由受控 seeder 建立；其他租戶須管理員明確啟用。
        if not bound_keys:
            return []

        available = []
        for module in all_modules:
            # 模組必須已 binding 啟用
            if module.module_key not in bound_keys:
                continue

            # 檢查角色
            if module.allowed_roles:
                if not any(r in user_roles for r in module.allowed_roles):
                    continue

            # 檢查部門
            if module.allowed_departments:
                if not any(str(d) in module.allowed_departments for d in user_department_ids):
                    continue

            # 檢查業務職能 allowlist（空 = 不限職能）
            if job_role_keys is not None:
                allowed_job = module.allowed_job_role_keys or []
                if allowed_job and not any(k in allowed_job for k in job_role_keys):
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
        from app.services.application_lifecycle import ApplicationLifecycleService

        binding = ApplicationLifecycleService(self.db).set_enabled_compat(
            tenant_id, module_key, enabled=True
        )
        if config:
            envelope = dict(binding.config_json or {})
            lifecycle = envelope.get("_application_lifecycle")
            envelope.update(config)
            if lifecycle is not None:
                envelope["_application_lifecycle"] = lifecycle
            binding.config_json = envelope

        self.db.commit()
        logger.info(f"Module {module_key} enabled for tenant {tenant_id}")
        return True

    def disable_module(self, tenant_id: UUID, module_key: str) -> bool:
        """停用租戶模組。"""
        from app.services.application_lifecycle import ApplicationLifecycleService

        ApplicationLifecycleService(self.db).set_enabled_compat(
            tenant_id, module_key, enabled=False
        )
        self.db.commit()
        logger.info(f"Module {module_key} disabled for tenant {tenant_id}")
        return True

    def update_config(
        self,
        tenant_id: UUID,
        module_key: str,
        config: Dict[str, Any],
    ) -> bool:
        """更新租戶模組設定。"""
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
            envelope = dict(config)
            lifecycle = dict(
                (binding.config_json or {}).get("_application_lifecycle") or {}
            )
            if lifecycle:
                envelope["_application_lifecycle"] = lifecycle
            binding.config_json = envelope
            self.db.commit()
            return True
        return False

    # ── 租戶 config：版本化 merge + 驗證（Phase 1）──

    @staticmethod
    def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(base)
        for key, value in (override or {}).items():
            if isinstance(value, dict) and isinstance(out.get(key), dict):
                out[key] = ModuleRegistry._deep_merge(out[key], value)
            else:
                out[key] = value
        return out

    def validate_module_config(self, module_key: str, config: Dict[str, Any]) -> List[str]:
        """以正式模組的 default_config 為 schema：鍵必須已知、型別必須一致。

        回傳錯誤清單（空 = 通過）。租戶自訂模組（無 default_config）不做鍵限制。
        """
        from app.services.mka_module_seed import canonical_default_config

        defaults = canonical_default_config(module_key)
        errors: List[str] = []
        if not isinstance(config, dict):
            return ["config 必須是 JSON object"]
        if not defaults:
            return errors
        for key, value in config.items():
            if key not in defaults:
                errors.append(f"未知設定鍵：{key}")
                continue
            expected = defaults[key]
            # bool 是 int 子類，需先排除
            if isinstance(expected, bool):
                if not isinstance(value, bool):
                    errors.append(f"{key} 應為 bool，收到 {type(value).__name__}")
            elif isinstance(expected, int):
                if not isinstance(value, int) or isinstance(value, bool):
                    errors.append(f"{key} 應為 int，收到 {type(value).__name__}")
            elif isinstance(expected, str):
                if not isinstance(value, str):
                    errors.append(f"{key} 應為 str，收到 {type(value).__name__}")
            elif isinstance(expected, list):
                if not isinstance(value, list):
                    errors.append(f"{key} 應為 list，收到 {type(value).__name__}")
        return errors

    def get_effective_config(self, tenant_id: UUID, module_key: str) -> Dict[str, Any]:
        """effective config = canonical defaults ← 租戶 config_json（含版本號）。"""
        from app.models.mka import TenantModuleBinding
        from app.services.mka_module_seed import canonical_default_config

        binding = (
            self.db.query(TenantModuleBinding)
            .filter(
                TenantModuleBinding.tenant_id == tenant_id,
                TenantModuleBinding.module_key == module_key,
            )
            .first()
        )
        defaults = canonical_default_config(module_key)
        override = (binding.config_json if binding else None) or {}
        return {
            "module_key": module_key,
            "config_version": binding.config_version if binding else 0,
            "enabled": bool(binding.enabled) if binding else False,
            "defaults": defaults,
            "overrides": override,
            "effective": self._deep_merge(defaults, override),
        }

    def update_config_versioned(
        self,
        tenant_id: UUID,
        module_key: str,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """驗證後寫入租戶 config 並遞增版本。驗證失敗 raise ValueError。"""
        from app.models.mka import TenantModuleBinding

        errors = self.validate_module_config(module_key, config)
        if errors:
            raise ValueError("；".join(errors))

        binding = (
            self.db.query(TenantModuleBinding)
            .filter(
                TenantModuleBinding.tenant_id == tenant_id,
                TenantModuleBinding.module_key == module_key,
            )
            .first()
        )
        if binding is None:
            binding = TenantModuleBinding(
                tenant_id=tenant_id,
                module_key=module_key,
                enabled=False,
                license_state="trial",
                config_json={},
                config_version=0,
            )
            self.db.add(binding)
            self.db.flush()
        binding.config_json = config
        binding.config_version = (binding.config_version or 0) + 1
        self.db.commit()
        return self.get_effective_config(tenant_id, module_key)

    def get_interaction_capabilities(self, tenant_id: UUID) -> Dict[str, bool]:
        """取得租戶的 interaction capabilities（誠實狀態）。"""
        from app.config import settings

        # QR：scene resolve API + QrScanner 前端已接線
        # camera／offline：PWA mediaDevices + service worker 已存在於前端
        return {
            "voice": bool(settings.VOICE_STT_ENABLED),
            "camera": True,
            "qr": True,
            "offline": True,
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
            "allowed_job_role_keys": module.allowed_job_role_keys or [],
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
