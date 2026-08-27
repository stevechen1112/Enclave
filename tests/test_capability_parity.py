"""Server-owned experience composition contract tests (Phase L)."""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.api.v1.endpoints.experience import (
    _ROLE_CAPS,
    _capabilities_for,
    _default_home,
    _filter_task_workspace_entries,
    _primary_navigation,
)

FRONTEND_CAPS_FILE = Path(__file__).resolve().parent.parent / "frontend" / "src" / "navigation" / "capabilities.ts"


def _parse_frontend_capability_union() -> set[str]:
    text = FRONTEND_CAPS_FILE.read_text(encoding="utf-8")
    match = re.search(r"export type Capability\s*=\s*(.*?);", text, re.DOTALL)
    assert match, "frontend Capability union not found"
    return set(re.findall(r"'([\w]+)'", match.group(1)))


def test_frontend_has_no_role_capability_authority():
    text = FRONTEND_CAPS_FILE.read_text(encoding="utf-8")
    assert "ROLE_CAPS" not in text
    assert "capabilitiesFor" not in text


def test_backend_caps_within_frontend_contract_union():
    union = _parse_frontend_capability_union()
    for role, caps in _ROLE_CAPS.items():
        assert set(caps) <= union, f"role={role} contains an unknown frontend capability"


@pytest.mark.parametrize(
    ("role", "superuser", "expected_paths"),
    [
        ("owner", False, ["/overview", "/ask", "/knowledge", "/governance", "/system"]),
        ("admin", False, ["/overview", "/ask", "/knowledge", "/governance", "/system"]),
        ("hr", False, ["/overview", "/ask", "/knowledge"]),
        ("employee", False, ["/overview", "/ask", "/knowledge"]),
        ("viewer", False, ["/overview", "/ask", "/knowledge"]),
        ("viewer", True, ["/overview", "/ask", "/knowledge", "/governance", "/system"]),
    ],
)
def test_six_personas_use_server_composed_base_navigation(role: str, superuser: bool, expected_paths: list[str]):
    caps = _capabilities_for(MagicMock(role=role, is_superuser=superuser))
    assert "field_work" not in caps
    assert [item["to"] for item in _primary_navigation(caps, [])] == expected_paths


def test_mka_navigation_is_added_only_by_enabled_ui_manifest():
    caps = _capabilities_for(MagicMock(role="employee", is_superuser=False))
    manifest = {"pack_key": "mka", "ui_key": "mka.workspace", "navigation": [{"to": "/job", "label": "現場作業"}]}
    navigation = _primary_navigation(caps + ["field_work"], [manifest])
    assert [item["to"] for item in navigation] == ["/overview", "/job", "/ask", "/knowledge"]
    assert navigation[1]["module"] == "mka.workspace"
    manifest["default_home"] = "/job"
    assert _default_home(caps + ["field_work"], [manifest], navigation) == "job"


def test_future_second_pack_composes_without_core_route_changes():
    caps = _capabilities_for(MagicMock(role="viewer", is_superuser=False))
    manifest = {"pack_key": "quality", "ui_key": "quality.workspace", "navigation": [{"to": "/quality-work", "label": "品質工作"}]}
    navigation = _primary_navigation(caps, [manifest])
    assert navigation[1] == {"to": "/quality-work", "label": "品質工作", "module": "quality.workspace"}


def test_pack_default_home_must_be_in_authorized_navigation():
    caps = _capabilities_for(MagicMock(role="employee", is_superuser=False))
    navigation = _primary_navigation(caps, [])
    assert _default_home(caps, [{"default_home": "/hidden-pack"}], navigation) == "overview"


def test_superuser_elevation_caps_exist_in_frontend_union():
    union = _parse_frontend_capability_union()
    caps = set(_capabilities_for(MagicMock(role="viewer", is_superuser=True)))
    assert caps <= union
    assert {"system_ops", "governance", "admin_home"} <= caps


def test_workspace_task_entries_are_filtered_by_runtime_access():
    entries = [
        {"label": "新人訓練", "path": "/job/tasks/training"},
        {"label": "訪談建卡", "path": "/job/tasks/interview"},
        {"label": "師傅經驗", "path": "/knowhow"},
        {"label": "設備維修", "path": "/forms/equipment_repair"},
    ]
    assert _filter_task_workspace_entries(entries, {"training"}) == [entries[0], entries[2], entries[3]]


def test_bootstrap_response_contract_keys():
    from unittest.mock import patch

    from app.api.v1.endpoints.experience import experience_bootstrap
    from app.config import settings

    db = MagicMock()
    user = MagicMock(
        id="00000000-0000-0000-0000-000000000001", email="a@b.c", full_name="Admin",
        role="owner", tenant_id="00000000-0000-0000-0000-000000000002",
        is_superuser=False, department_id=None, department=None,
    )
    with (
        patch.object(settings, "PACK_MKA_ENABLED", False),
        patch("app.services.deployment_mode.resolve_runtime_profiles", return_value={"main": {"provider": "ollama"}}),
    ):
        data = experience_bootstrap(db=db, current_user=user)
    expected_top = {
        "product", "user", "capabilities", "default_home", "primary_navigation", "packs",
        "inference", "features", "job_modules", "workspace_entries", "job_role_assignments",
        "active_job_role", "default_job_home", "interaction_capabilities", "ui_modules",
        "pack_permissions", "capability_catalog",
    }
    assert expected_top <= set(data)
    assert data["default_home"] == "overview"
    assert "/job" not in {item["to"] for item in data["primary_navigation"]}
    assert "field_work" not in data["capabilities"]
