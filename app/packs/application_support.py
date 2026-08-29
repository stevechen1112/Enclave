"""Shared tenant entitlement adapter for independently deployed applications."""

from __future__ import annotations

from sqlalchemy import func, or_

from app.platform.packs import PackTenantContext


class ModuleTenantEligibility:
    def __init__(self, module_key: str):
        self.module_key = module_key

    def is_enabled(self, context: PackTenantContext) -> bool:
        if context.module_key is not None and context.module_key != self.module_key:
            return False
        from app.models.mka import TenantModuleBinding

        rows = context.db.query(TenantModuleBinding).filter(
            TenantModuleBinding.tenant_id == context.tenant_id,
            TenantModuleBinding.module_key == self.module_key,
            TenantModuleBinding.enabled.is_(True),
            TenantModuleBinding.license_state.in_(["trial", "active"]),
            or_(
                TenantModuleBinding.effective_from.is_(None),
                TenantModuleBinding.effective_from <= func.now(),
            ),
            or_(
                TenantModuleBinding.effective_to.is_(None),
                TenantModuleBinding.effective_to > func.now(),
            ),
        ).all()
        for binding in rows:
            lifecycle = dict(
                (binding.config_json or {}).get("_application_lifecycle") or {}
            )
            if lifecycle and lifecycle.get("state") != "enabled":
                continue
            return True
        return False
