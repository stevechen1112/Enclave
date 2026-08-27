"""Explicit MKA provisioning lifecycle; never invoked by a GET endpoint."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session


def provision_tenant(
    db: Session,
    *,
    tenant_id: UUID,
    enable_default_modules: bool = False,
) -> dict[str, int]:
    from app.services.mka_module_seed import (
        ensure_tenant_module_bindings,
        seed_canonical_modules,
        seed_canonical_task_definitions,
        seed_default_job_roles,
    )

    result = {
        "modules": seed_canonical_modules(db),
        "tasks": seed_canonical_task_definitions(db),
        "job_roles": seed_default_job_roles(db, tenant_id),
        "bindings": 0,
    }
    if enable_default_modules:
        result["bindings"] = ensure_tenant_module_bindings(db, tenant_id)
    return result
