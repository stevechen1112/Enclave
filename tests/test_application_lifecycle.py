from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.composition.packs import build_pack_registry
from app.models.mka import TenantModuleBinding
from app.models.tenant import Tenant
from app.platform.packs import PackTenantContext
from app.services.application_lifecycle import (
    ApplicationLifecycleError,
    ApplicationLifecycleService,
)


@pytest.fixture()
def lifecycle_db():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Tenant.__table__.create(engine)
    TenantModuleBinding.__table__.create(engine)
    db = sessionmaker(bind=engine)()
    tenant = Tenant(name=f"lifecycle-{uuid4().hex[:6]}")
    db.add(tenant)
    db.flush()
    try:
        yield db, tenant
    finally:
        db.close()
        engine.dispose()


def _enabled(registry, db, tenant, module_key):
    return registry.is_enabled_for_tenant(
        "mka",
        context=PackTenantContext(
            tenant_id=tenant.id, db=db, module_key=module_key
        ),
    )


def test_disable_archive_remove_fail_closed_without_affecting_other_app(lifecycle_db):
    db, tenant = lifecycle_db
    service = ApplicationLifecycleService(db)
    registry = build_pack_registry(deployment_capabilities={"mka": True})
    service.install(tenant.id, "sales_quote")
    service.enable(tenant.id, "sales_quote")
    service.install(tenant.id, "quality_8d")
    service.enable(tenant.id, "quality_8d")
    assert _enabled(registry, db, tenant, "sales_quote")
    assert _enabled(registry, db, tenant, "quality_8d")

    service.disable(tenant.id, "sales_quote")
    assert not _enabled(registry, db, tenant, "sales_quote")
    assert _enabled(registry, db, tenant, "quality_8d")
    service.archive(tenant.id, "sales_quote")
    with pytest.raises(ApplicationLifecycleError, match="export receipt"):
        service.remove(
            tenant.id, "sales_quote", data_disposition="delete"
        )
    with pytest.raises(ApplicationLifecycleError, match="disposition receipt"):
        service.remove(
            tenant.id,
            "sales_quote",
            export_receipt="export:tenant/sales_quote/20260829",
            data_disposition="delete",
        )
    removed = service.remove(
        tenant.id,
        "sales_quote",
        export_receipt="export:tenant/sales_quote/20260829",
        data_disposition="delete",
        data_disposition_receipt="purge:sales_quote/20260829",
    )
    assert service.state(removed) == "removed"
    assert not _enabled(registry, db, tenant, "sales_quote")
    assert _enabled(registry, db, tenant, "quality_8d")


def test_retained_knowledge_application_requires_retain_disposition(lifecycle_db):
    db, tenant = lifecycle_db
    service = ApplicationLifecycleService(db)
    service.install(tenant.id, "training_knowhow")
    service.archive(tenant.id, "training_knowhow")
    with pytest.raises(ApplicationLifecycleError, match="data disposition"):
        service.remove(
            tenant.id, "training_knowhow", data_disposition="delete"
        )
    binding = service.remove(
        tenant.id, "training_knowhow", data_disposition="retain"
    )
    assert service.state(binding) == "removed"


def test_lifecycle_rejects_unknown_and_invalid_transitions(lifecycle_db):
    db, tenant = lifecycle_db
    service = ApplicationLifecycleService(db)
    with pytest.raises(ApplicationLifecycleError, match="unknown application"):
        service.install(tenant.id, "unknown")
    service.install(tenant.id, "quality_8d")
    with pytest.raises(ApplicationLifecycleError, match="invalid application transition"):
        service.disable(tenant.id, "quality_8d")


def test_legacy_boolean_cannot_revive_removed_application(lifecycle_db):
    db, tenant = lifecycle_db
    service = ApplicationLifecycleService(db)
    registry = build_pack_registry(deployment_capabilities={"mka": True})
    service.set_enabled_compat(tenant.id, "sales_quote", enabled=True)
    service.set_enabled_compat(tenant.id, "sales_quote", enabled=False)
    service.archive(tenant.id, "sales_quote")
    binding = service.remove(
        tenant.id,
        "sales_quote",
        export_receipt="export:receipt",
        data_disposition="delete",
        data_disposition_receipt="purge:receipt",
    )
    # Even a direct legacy-column mutation cannot bypass lifecycle metadata.
    binding.enabled = True
    binding.license_state = "active"
    db.flush()
    assert not _enabled(registry, db, tenant, "sales_quote")
    with pytest.raises(ApplicationLifecycleError, match="removed"):
        service.set_enabled_compat(tenant.id, "sales_quote", enabled=True)
