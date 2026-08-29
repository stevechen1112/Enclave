"""Composition adapter between core applicability and optional Pack entitlement."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.composition.packs import build_pack_registry
from app.platform.packs import PackTenantContext


def is_application_module_enabled(
    *, db: Any, tenant_id: UUID, module_key: str
) -> bool:
    registry = build_pack_registry()
    pack_key = registry.pack_key_for_module(module_key)
    if pack_key is None:
        return False
    return registry.is_enabled_for_tenant(
        pack_key,
        context=PackTenantContext(
            tenant_id=tenant_id,
            db=db,
            module_key=module_key,
        ),
    )
