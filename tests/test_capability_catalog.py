from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.platform.packs import PackContribution, PackManifest, PackRegistry
from app.services.capability_catalog import build_capability_catalog


def _registry(*, deployed: bool) -> PackRegistry:
    pack = PackContribution(
        manifest=PackManifest(
            pack_key="quality",
            pack_version="1.0.0",
            display_name="Quality",
            capability_keys=("quality.read",),
            module_keys=("quality_8d",),
            permission_keys=("quality.workspace.read",),
            tenant_binding_required=False,
        )
    )
    return PackRegistry([pack], deployment_capabilities={"quality": deployed})


def test_catalog_preserves_four_independent_states():
    with patch("app.services.capability_catalog.module_status", return_value={"enclave_base": True}):
        entries = build_capability_catalog(
            MagicMock(), tenant_id=uuid4(), pack_registry=_registry(deployed=True),
            runtime_snapshot={"packs": {"enclave_base": {"state": "healthy"}, "quality": {"state": "degraded"}}},
            user_permissions={"quality.workspace.read"},
        )
    assert entries == [
        {"key": "enclave_base", "kind": "platform_capability", "deployment_status": "deployed", "entitlement_status": "included", "runtime_status": "healthy", "user_permission_status": "not_applicable"},
        {"key": "quality_8d", "pack_key": "quality", "kind": "domain_module", "deployment_status": "deployed", "entitlement_status": "enabled", "runtime_status": "degraded", "user_permission_status": "allowed"},
    ]


def test_catalog_never_turns_deployment_into_user_permission():
    with patch("app.services.capability_catalog.module_status", return_value={}):
        entry = build_capability_catalog(
            MagicMock(), tenant_id=uuid4(), pack_registry=_registry(deployed=False), user_permissions={"quality.workspace.read"}
        )[0]
    assert entry["deployment_status"] == "not_deployed"
    assert entry["entitlement_status"] == "disabled"
    assert entry["user_permission_status"] == "denied"


def test_pack_can_supply_effective_per_module_access():
    with patch("app.services.capability_catalog.module_status", return_value={}):
        entry = build_capability_catalog(
            MagicMock(), tenant_id=uuid4(), pack_registry=_registry(deployed=True),
            user_permissions={"quality.workspace.read"},
            accessible_modules_by_pack={"quality": set()},
        )[0]
    assert entry["entitlement_status"] == "enabled"
    assert entry["user_permission_status"] == "denied"
