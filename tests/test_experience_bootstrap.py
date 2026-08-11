"""UX experience bootstrap — capabilities & honesty surface."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.api.v1.endpoints.experience import (
    _capabilities_for,
    _inference_boundary,
    _pack_states,
    experience_bootstrap,
)


def test_capabilities_admin_has_admin_home():
    user = MagicMock()
    user.role = "admin"
    user.is_superuser = False
    caps = _capabilities_for(user)
    assert "admin_home" in caps
    assert "review_queue" in caps
    assert "ask" in caps


def test_capabilities_employee_no_review():
    user = MagicMock()
    user.role = "employee"
    user.is_superuser = False
    caps = _capabilities_for(user)
    assert "ask" in caps
    assert "review_queue" not in caps
    assert "admin_home" not in caps


def test_capabilities_unknown_role_least_privilege():
    user = MagicMock()
    user.role = "manager"  # not a formal role
    user.is_superuser = False
    caps = _capabilities_for(user)
    assert caps == _capabilities_for(MagicMock(role="employee", is_superuser=False))


def test_pack_states_includes_certified_nas():
    packs = _pack_states()
    assert packs["certified_connectors"]["items"] == ["nas_smb"]
    assert "sharepoint" in packs["certified_connectors"]["not_certified"]


def test_inference_boundary_external():
    db = MagicMock()
    with patch(
        "app.services.deployment_mode.resolve_runtime_profiles",
        return_value={"main": {"provider": "gemini"}},
    ):
        inf = _inference_boundary(db)
    assert inf["mode"] == "external_model"
    assert inf["data_stays_on_prem_for_inference"] is False


def test_inference_boundary_local():
    db = MagicMock()
    with patch(
        "app.services.deployment_mode.resolve_runtime_profiles",
        return_value={"main": {"provider": "ollama"}},
    ):
        inf = _inference_boundary(db)
    assert inf["mode"] == "local_model"
    assert inf["data_stays_on_prem_for_inference"] is True


def test_bootstrap_shape():
    db = MagicMock()
    user = MagicMock()
    user.id = "00000000-0000-0000-0000-000000000001"
    user.email = "a@b.c"
    user.full_name = "Admin"
    user.role = "owner"
    user.tenant_id = "00000000-0000-0000-0000-000000000002"
    user.is_superuser = False
    # bootstrap 現在走真實 AuthorizationContext.from_user；未設定的 MagicMock
    # department 會無限生成 parent mock 導致祖先遍歷永遠不停
    user.department_id = None
    user.department = None
    with patch(
        "app.services.deployment_mode.resolve_runtime_profiles",
        return_value={"main": {"provider": "ollama"}},
    ):
        data = experience_bootstrap(db=db, current_user=user)
    assert data["product"]["maturity"] == "pilot"
    assert data["default_home"] == "overview"
    assert data["features"]["sso"] is False
    assert data["features"]["wiki_editor"] is False
    assert "ask" in data["capabilities"]
