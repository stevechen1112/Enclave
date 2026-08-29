from __future__ import annotations

import importlib
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import APIRouter
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.composition.knowledge import build_knowledge_provider_registry
from app.composition.pack_surfaces import (
    import_pack_task_modules,
    include_pack_routers,
    load_contribution_object,
)
from app.composition.packs import build_pack_registry
from app.models.mka import TenantModuleBinding
from app.models.tenant import Tenant
from app.platform.packs import (
    ApplicationDataPolicy,
    ApplicationManifest,
    PackContribution,
    PackDependency,
    PackManifest,
    PackRegistry,
    PackTenantContext,
    UIModuleContribution,
)


def _pack(
    key: str,
    *,
    version: str = "1.0.0",
    dependencies: tuple[PackDependency, ...] = (),
) -> PackContribution:
    return PackContribution(
        manifest=PackManifest(
            pack_key=key,
            pack_version=version,
            display_name=key,
            capability_keys=(f"{key}.read",),
            dependencies=dependencies,
            tenant_binding_required=False,
        )
    )


@pytest.fixture()
def pack_db():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Tenant.__table__.create(engine)
    TenantModuleBinding.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_mka_manifest_registers_all_backend_contribution_types():
    registry = build_pack_registry(deployment_capabilities={"mka": True})
    contribution = registry.get("mka")

    assert registry.deployed_pack_keys == (
        "mka",
        "sales_quote",
        "incident_handover",
        "quality_8d",
        "training_knowhow",
    )
    assert contribution is not None
    assert contribution.manifest.pack_version == "1.0.0"
    assert contribution.manifest.module_keys == ()
    assert [provider.provider_key for provider in registry.knowledge_providers()] == [
        "mka.approved_knowhow"
    ]
    assert len(registry.task_handlers()) == 2
    assert len(registry.projectors()) == 2
    assert [item.router_key for item in registry.api_routers()] == ["mka.api"]
    assert [item.resolver_key for item in registry.permission_resolvers()] == [
        "mka.permissions"
    ]
    assert [item.hook_key for item in registry.lifecycle_hooks()] == [
        "mka.tenant.provision"
    ]
    assert [item.ui_key for item in registry.ui_modules()] == [
        "mka.workspace",
        "sales_quote.entry",
        "training_knowhow.workspace",
    ]
    assert "mka.module.admin" in registry.permission_keys()


def test_mka_apps_have_independent_versioned_contracts_and_data_policies():
    registry = build_pack_registry(deployment_capabilities={"mka": True})
    applications = [
        application
        for pack_key in registry.pack_keys
        for application in (registry.get(pack_key).applications if registry.get(pack_key) else ())
    ]
    assert [app.application_key for app in applications] == [
        "sales.quote",
        "operations.incident_handover",
        "quality.8d",
        "training.knowhow",
    ]
    assert {
        app.module_key for app in applications
    } == {"sales_quote", "incident_handover", "quality_8d", "training_knowhow"}
    all_handlers = [
        key for app in applications for key in app.handler_keys
    ]
    assert len(all_handlers) == len(set(all_handlers))
    for app in applications:
        assert app.application_version == "1.0.0"
        assert app.data_policy is not None
        assert registry.application_for_module(app.module_key) is app
        owner = registry.get(registry.pack_key_for_module(app.module_key))
        assert owner is not None
        assert set(app.required_platform_capability_keys).issubset(
            owner.manifest.required_platform_capability_keys
        )


def test_application_contract_requires_full_lifecycle_and_data_policy():
    common = dict(
        application_key="test.app",
        application_version="1.0.0",
        display_name="Test",
        module_key="test_app",
        owned_capability_keys=("test.app.use",),
        required_platform_capability_keys=("workflow.task",),
    )
    with pytest.raises(ValueError, match="data_policy"):
        ApplicationManifest(**common)
    with pytest.raises(ValueError, match="lifecycle"):
        ApplicationManifest(
            **common,
            data_policy=ApplicationDataPolicy(ownership_key="test.records"),
            lifecycle_events=("application.enable",),
        )


def test_task_handler_descriptors_resolve_to_existing_callables():
    registry = build_pack_registry(deployment_capabilities={"mka": True})
    for descriptor in registry.task_handlers():
        module_name, attribute = descriptor.handler_path.rsplit(".", 1)
        assert callable(getattr(importlib.import_module(module_name), attribute))
    for descriptor in registry.projectors():
        module_name, attribute = descriptor.projector_path.rsplit(".", 1)
        assert callable(getattr(importlib.import_module(module_name), attribute))
    for descriptor in (
        registry.workflow_handler(key, module)
        for key, module in (
            ("quote", "sales_quote"),
            ("incident", "incident_handover"),
            ("quality_8d", "quality_8d"),
            ("interview", "training_knowhow"),
        )
    ):
        assert descriptor is not None
        module_name, attribute = descriptor.handler_path.split(":", 1)
        assert callable(getattr(importlib.import_module(module_name), attribute))


def test_deployment_flag_removes_every_mka_backend_contribution():
    registry = build_pack_registry(deployment_capabilities={"mka": False})

    assert registry.pack_keys == (
        "mka",
        "sales_quote",
        "incident_handover",
        "quality_8d",
        "training_knowhow",
    )
    assert registry.deployed_pack_keys == ()
    assert registry.knowledge_providers() == ()
    assert registry.task_handlers() == ()
    assert registry.projectors() == ()
    assert registry.ui_modules() == ()
    assert registry.api_routers() == ()
    assert registry.permission_resolvers() == ()
    assert registry.lifecycle_hooks() == ()
    assert registry.permission_keys() == ()


def test_one_application_pack_can_be_physically_excluded() -> None:
    registry = build_pack_registry(
        deployment_capabilities={"mka": True, "sales_quote": False}
    )
    assert "sales_quote" not in registry.deployed_pack_keys
    assert registry.workflow_handler("quote", "sales_quote") is None
    assert registry.workflow_handler("quality_8d", "quality_8d") is not None
    assert "sales_quote.entry" not in {
        item.ui_key for item in registry.ui_modules()
    }
    assert "training_knowhow.workspace" in {
        item.ui_key for item in registry.ui_modules()
    }


def test_disabled_pack_has_no_api_or_worker_surface():
    disabled = build_pack_registry(deployment_capabilities={"mka": False})
    router = APIRouter()
    include_pack_routers(router, disabled)

    assert router.routes == []
    assert import_pack_task_modules(disabled) == ()


def test_enabled_pack_owns_compatible_api_and_callable_hooks():
    enabled = build_pack_registry(deployment_capabilities={"mka": True})
    router = APIRouter()
    include_pack_routers(router, enabled)
    effective_routes = []
    for route in router.routes:
        route_contexts = getattr(route, "effective_route_contexts", None)
        if callable(route_contexts):
            effective_routes.extend(route_contexts())
        else:
            effective_routes.append(route)
    paths = {route.path for route in effective_routes}

    assert "/knowhow" in paths
    assert "/job-modules" in paths
    assert "/knowledge-captures" not in paths
    for item in (*enabled.permission_resolvers(), *enabled.lifecycle_hooks()):
        path = getattr(item, "resolver_path", None) or item.hook_path
        assert callable(load_contribution_object(path))


def test_knowledge_composition_honors_pack_deployment_flag(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "PACK_MKA_ENABLED", False)
    assert build_knowledge_provider_registry().provider_keys == (
        "core.video_procedure",
    )


def test_tenant_binding_is_separate_from_deployment_capability(pack_db):
    tenant = Tenant(name=f"tenant-{uuid4().hex[:6]}")
    pack_db.add(tenant)
    pack_db.flush()
    registry = build_pack_registry(deployment_capabilities={"mka": True})
    context = PackTenantContext(tenant_id=tenant.id, db=pack_db)

    assert not registry.is_enabled_for_tenant("mka", context=context)

    pack_db.add(
        TenantModuleBinding(
            tenant_id=tenant.id,
            module_key="training_knowhow",
            enabled=True,
            license_state="active",
        )
    )
    pack_db.flush()

    assert registry.is_enabled_for_tenant("mka", context=context)
    assert registry.is_enabled_for_tenant(
        "mka",
        context=PackTenantContext(
            tenant_id=tenant.id, db=pack_db, module_key="training_knowhow"
        ),
    )
    assert not registry.is_enabled_for_tenant(
        "mka",
        context=PackTenantContext(
            tenant_id=tenant.id, db=pack_db, module_key="quality_8d"
        ),
    )
    assert [
        ui.ui_key
        for _, ui in registry.enabled_ui_modules(
            context=PackTenantContext(tenant_id=tenant.id, db=pack_db)
        )
    ] == ["mka.workspace", "training_knowhow.workspace"]


def test_registry_rejects_missing_incompatible_and_circular_dependencies():
    with pytest.raises(ValueError, match="missing dependency"):
        PackRegistry(
            [
                _pack(
                    "feature",
                    dependencies=(PackDependency("core", "1.0.0"),),
                )
            ]
        )

    with pytest.raises(ValueError, match="disabled deployment dependency"):
        PackRegistry(
            [
                _pack("core"),
                _pack(
                    "feature",
                    dependencies=(PackDependency("core", "1.0.0"),),
                ),
            ],
            deployment_capabilities={"core": False, "feature": True},
        )

    with pytest.raises(ValueError, match="incompatible dependency"):
        PackRegistry(
            [
                _pack("core", version="1.0.0"),
                _pack(
                    "feature",
                    dependencies=(PackDependency("core", "2.0.0"),),
                ),
            ]
        )

    with pytest.raises(ValueError, match="circular"):
        PackRegistry(
            [
                _pack("alpha", dependencies=(PackDependency("beta", "1.0.0"),)),
                _pack("beta", dependencies=(PackDependency("alpha", "1.0.0"),)),
            ]
        )


def test_registry_is_immutable_after_composition():
    registry = PackRegistry([_pack("core")])
    with pytest.raises(RuntimeError, match="immutable"):
        registry.register(_pack("late"))


def test_registry_rejects_unknown_required_platform_capability():
    contribution = PackContribution(
        manifest=PackManifest(
            pack_key="broken",
            pack_version="1.0.0",
            display_name="Broken",
            capability_keys=("broken.use",),
            required_platform_capability_keys=("workflow.does_not_exist",),
            tenant_binding_required=False,
        )
    )
    with pytest.raises(ValueError, match="unknown required platform"):
        PackRegistry([contribution])


def test_registry_rejects_duplicate_ui_route_keys():
    def with_ui(pack_key: str, ui_key: str) -> PackContribution:
        return PackContribution(
            manifest=PackManifest(
                pack_key=pack_key,
                pack_version="1.0.0",
                display_name=pack_key,
                capability_keys=(f"{pack_key}.read",),
                tenant_binding_required=False,
            ),
            ui_modules=(
                UIModuleContribution(
                    ui_key=ui_key,
                    ui_version="1.0.0",
                    route_keys=("shared.route",),
                ),
            ),
        )

    with pytest.raises(ValueError, match="duplicate ui route"):
        PackRegistry([with_ui("alpha", "alpha.ui"), with_ui("beta", "beta.ui")])


def test_registry_assigns_one_pack_owner_per_application_module():
    def with_module(pack_key: str, module_key: str) -> PackContribution:
        return PackContribution(
            manifest=PackManifest(
                pack_key=pack_key,
                pack_version="1.0.0",
                display_name=pack_key,
                capability_keys=(f"{pack_key}.read",),
                module_keys=(module_key,),
                tenant_binding_required=False,
            )
        )

    registry = PackRegistry([with_module("quality", "quality_8d")])
    assert registry.pack_key_for_module("quality_8d") == "quality"
    assert registry.pack_key_for_module("missing") is None

    with pytest.raises(ValueError, match="duplicate module key"):
        PackRegistry(
            [
                with_module("quality", "shared_module"),
                with_module("operations", "shared_module"),
            ]
        )


def test_ui_default_home_must_be_one_of_its_navigation_paths():
    with pytest.raises(ValueError, match="default_home"):
        UIModuleContribution(
            ui_key="quality.ui",
            ui_version="1.0.0",
            route_keys=("quality.home",),
            navigation=({"to": "/quality", "label": "品質"},),
            default_home="/not-contributed",
        )


def test_platform_source_has_no_pack_internal_imports():
    platform_root = Path(__file__).parents[1] / "app" / "platform"
    violations = []
    for path in platform_root.rglob("*.py"):
        if "app.packs" in path.read_text(encoding="utf-8"):
            violations.append(path.relative_to(platform_root).as_posix())
    assert violations == []
