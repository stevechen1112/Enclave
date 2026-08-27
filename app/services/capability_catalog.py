"""Unified read model for deployment, entitlement and runtime capability state."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.platform.packs import PackRegistry, PackTenantContext
from app.services.product_license import module_status


def build_capability_catalog(
    db: Session,
    *,
    tenant_id: UUID,
    pack_registry: PackRegistry,
    runtime_snapshot: dict[str, Any] | None = None,
    user_permissions: set[str] | None = None,
    accessible_modules_by_pack: dict[str, set[str]] | None = None,
) -> list[dict[str, Any]]:
    """Return one catalog without collapsing its four independent states."""
    runtime = dict(runtime_snapshot or {})
    runtime_packs = dict(runtime.get("packs") or {})
    granted = set(user_permissions or ())
    module_access = accessible_modules_by_pack or {}
    entries: list[dict[str, Any]] = []
    for key, deployed in module_status().items():
        health = dict(runtime_packs.get(key) or {})
        entries.append(
            {
                "key": key,
                "kind": "platform_capability",
                "deployment_status": "deployed" if deployed else "not_deployed",
                "entitlement_status": "included" if deployed else "unavailable",
                "runtime_status": str(
                    health.get("state")
                    or ("unknown" if deployed else "not_deployed")
                ),
                "user_permission_status": "not_applicable",
            }
        )
    for pack_key in pack_registry.pack_keys:
        contribution = pack_registry.get(pack_key)
        if contribution is None:
            continue
        deployed = pack_registry.is_deployed(pack_key)
        pack_permissions = set(contribution.manifest.permission_keys)
        pack_allowed = bool(granted.intersection(pack_permissions))
        health = dict(runtime_packs.get(pack_key) or {})
        for module_key in contribution.manifest.module_keys or (pack_key,):
            user_allowed = (
                module_key in module_access[pack_key]
                if pack_key in module_access
                else pack_allowed
            )
            entitled = deployed and pack_registry.is_enabled_for_tenant(
                pack_key,
                context=PackTenantContext(
                    tenant_id=tenant_id,
                    db=db,
                    module_key=(
                        module_key if contribution.manifest.module_keys else None
                    ),
                ),
            )
            entries.append(
                {
                    "key": module_key,
                    "pack_key": pack_key,
                    "kind": "domain_module",
                    "deployment_status": "deployed" if deployed else "not_deployed",
                    "entitlement_status": "enabled" if entitled else "disabled",
                    "runtime_status": str(
                        health.get("state")
                        or ("unknown" if deployed else "not_deployed")
                    ),
                    "user_permission_status": (
                        "allowed" if entitled and user_allowed else "denied"
                    ),
                }
            )
    return entries
