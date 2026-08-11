"""
MKA-P4：職能模組平台化 — module registry admin + compatibility matrix。

對照 ENGINEERING_PLAN.md §8 MKA-P4：
- Module Registry admin
- tenant module enable/disable
- module version migration
- module usage dashboard
- module license/quota
- module export/import package
- module compatibility matrix

關鍵證明：新增第三模組時，不修改 chat.py、multi_step_orchestrator.py、核心 PEP。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass
class CompatibilityEntry:
    """模組相容性矩陣項目。"""
    module_key: str
    module_version: str
    enclave_version: str = "2.0"
    compatible: bool = True
    notes: str = ""
    required_packs: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "module_key": self.module_key,
            "module_version": self.module_version,
            "enclave_version": self.enclave_version,
            "compatible": self.compatible,
            "notes": self.notes,
            "required_packs": self.required_packs,
        }


class CompatibilityMatrix:
    """模組相容性矩陣 — 確保模組與 Enclave 版本相容。"""

    def __init__(self):
        self._entries: Dict[str, CompatibilityEntry] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        """註冊預設相容性。"""
        defaults = [
            ("spec_sop", "1.0", "2.0", True, "", []),
            ("sales_quote", "1.0", "2.0", True, "", []),
            ("incident_handover", "1.0", "2.0", True, "", []),
            ("quality_8d", "1.0", "2.0", True, "需 Knowledge Compiler pack", ["knowledge_compiler"]),
            ("training_knowhow", "1.0", "2.0", True, "需 Agent Automation pack", ["agent_automation"]),
        ]
        for key, ver, enclave, compat, notes, packs in defaults:
            entry = CompatibilityEntry(
                module_key=key, module_version=ver,
                enclave_version=enclave, compatible=compat,
                notes=notes, required_packs=packs,
            )
            self._entries[f"{key}:{ver}"] = entry

    def check_compatibility(
        self,
        module_key: str,
        module_version: str,
        enclave_version: str = "2.0",
        enabled_packs: Optional[List[str]] = None,
    ) -> Tuple[bool, str]:
        """檢查模組相容性。

        Returns:
            (compatible, reason)
        """
        entry = self._entries.get(f"{module_key}:{module_version}")
        if entry is None:
            return False, f"Module {module_key}:{module_version} not in compatibility matrix"

        if not entry.compatible:
            return False, f"Module {module_key}:{module_version} is marked incompatible"

        # 檢查 required packs
        if entry.required_packs and enabled_packs is not None:
            missing = [p for p in entry.required_packs if p not in enabled_packs]
            if missing:
                return False, f"Missing required packs: {missing}"

        return True, "compatible"

    def list_entries(self) -> List[Dict[str, Any]]:
        return [e.to_dict() for e in self._entries.values()]

    def add_entry(self, entry: CompatibilityEntry) -> None:
        self._entries[f"{entry.module_key}:{entry.module_version}"] = entry


class ModuleAdminService:
    """模組管理服務 — admin 操作。"""

    def __init__(self, db: Session):
        self.db = db
        self.compatibility = CompatibilityMatrix()

    def register_module(
        self,
        module_key: str,
        name: str,
        description: str = "",
        allowed_roles: Optional[List[str]] = None,
        allowed_departments: Optional[List[str]] = None,
        allowed_tools: Optional[List[str]] = None,
        supported_intents: Optional[List[str]] = None,
        form_definition_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """註冊新模組（admin）。"""
        from app.models.mka import JobModule

        existing = (
            self.db.query(JobModule)
            .filter(JobModule.module_key == module_key, JobModule.tenant_id.is_(None))
            .first()
        )
        if existing:
            # 更新
            existing.name = name
            existing.description = description
            if allowed_roles is not None:
                existing.allowed_roles = allowed_roles
            if allowed_departments is not None:
                existing.allowed_departments = allowed_departments
            if allowed_tools is not None:
                existing.allowed_tools = allowed_tools
            if supported_intents is not None:
                existing.supported_intents = supported_intents
            if form_definition_ids is not None:
                existing.form_definition_ids = form_definition_ids
            self.db.commit()
            return {"id": str(existing.id), "module_key": module_key, "action": "updated"}

        module = JobModule(
            module_key=module_key,
            tenant_id=None,  # 全租戶可用
            name=name,
            description=description,
            version="1.0",
            status="draft",
            allowed_roles=allowed_roles or [],
            allowed_departments=allowed_departments or [],
            allowed_tools=allowed_tools or [],
            supported_intents=supported_intents or [],
            form_definition_ids=form_definition_ids or [],
        )
        self.db.add(module)
        self.db.commit()
        logger.info(f"Module registered: {module_key}")
        return {"id": str(module.id), "module_key": module_key, "action": "created"}

    def enable_for_tenant(
        self,
        tenant_id: UUID,
        module_key: str,
        config: Optional[Dict[str, Any]] = None,
        enabled_packs: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """啟用租戶模組（含相容性檢查）。"""
        # 相容性檢查
        compatible, reason = self.compatibility.check_compatibility(
            module_key, "1.0", enabled_packs=enabled_packs
        )
        if not compatible:
            return {"enabled": False, "reason": reason}

        from app.services.module_registry import get_module_registry
        registry = get_module_registry(self.db)
        registry.enable_module(tenant_id, module_key, config)

        return {"enabled": True, "module_key": module_key, "tenant_id": str(tenant_id)}

    def disable_for_tenant(self, tenant_id: UUID, module_key: str) -> Dict[str, Any]:
        """停用租戶模組。"""
        from app.services.module_registry import get_module_registry
        registry = get_module_registry(self.db)
        success = registry.disable_module(tenant_id, module_key)
        return {"disabled": success, "module_key": module_key}

    def list_tenant_modules(self, tenant_id: UUID) -> List[Dict[str, Any]]:
        """列出租戶已啟用的模組。"""
        from app.models.mka import TenantModuleBinding

        bindings = (
            self.db.query(TenantModuleBinding)
            .filter(TenantModuleBinding.tenant_id == tenant_id)
            .all()
        )
        return [
            {
                "module_key": b.module_key,
                "module_version": b.module_version,
                "enabled": b.enabled,
                "license_state": b.license_state,
                "config": b.config_json or {},
            }
            for b in bindings
        ]

    def get_compatibility_matrix(self) -> List[Dict[str, Any]]:
        """取得相容性矩陣。"""
        return self.compatibility.list_entries()


# ── 單例 ──

_matrix: Optional[CompatibilityMatrix] = None


def get_compatibility_matrix() -> CompatibilityMatrix:
    global _matrix
    if _matrix is None:
        _matrix = CompatibilityMatrix()
    return _matrix