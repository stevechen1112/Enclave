"""前後端 capability 契約一致性（Phase 0 雙軌修復的快照測試）。

bootstrap（後端 `_ROLE_CAPS`）是能力唯一來源；前端 `ROLE_CAPS` 僅為
bootstrap 未載入時的 route-guard fallback。兩份表必須逐角色一致，
否則會出現「選單看得到但 API 擋下」或反過來的雙軌漂移。
"""
from __future__ import annotations

import re
from pathlib import Path

from app.api.v1.endpoints.experience import _ROLE_CAPS

FRONTEND_CAPS_FILE = (
    Path(__file__).resolve().parent.parent
    / "frontend" / "src" / "navigation" / "capabilities.ts"
)

FORMAL_ROLES = ["owner", "admin", "hr", "employee", "viewer"]


def _parse_frontend_role_caps() -> dict:
    text = FRONTEND_CAPS_FILE.read_text(encoding="utf-8")
    m = re.search(
        r"const ROLE_CAPS:\s*Record<FormalRole,\s*Capability\[\]>\s*=\s*\{(.*?)\n\}",
        text,
        re.S,
    )
    assert m, "frontend ROLE_CAPS block not found"
    body = m.group(1)
    out: dict = {}
    for role_match in re.finditer(r"(\w+):\s*\[(.*?)\]", body, re.S):
        role = role_match.group(1)
        caps = re.findall(r"'([\w]+)'", role_match.group(2))
        out[role] = set(caps)
    return out


def _parse_frontend_capability_union() -> set:
    text = FRONTEND_CAPS_FILE.read_text(encoding="utf-8")
    m = re.search(r"export type Capability\s*=\s*(.*?);", text, re.S)
    assert m, "frontend Capability union not found"
    return set(re.findall(r"'([\w]+)'", m.group(1)))


def test_role_caps_parity_with_frontend():
    frontend = _parse_frontend_role_caps()
    assert set(frontend.keys()) == set(FORMAL_ROLES), (
        f"frontend ROLE_CAPS roles drifted: {sorted(frontend.keys())}"
    )
    for role in FORMAL_ROLES:
        backend_caps = set(_ROLE_CAPS[role])
        frontend_caps = frontend[role]
        assert backend_caps == frontend_caps, (
            f"role={role} capability drift: "
            f"backend_only={sorted(backend_caps - frontend_caps)} "
            f"frontend_only={sorted(frontend_caps - backend_caps)}"
        )


def test_backend_caps_within_frontend_capability_union():
    union = _parse_frontend_capability_union()
    for role, caps in _ROLE_CAPS.items():
        unknown = set(caps) - union
        assert not unknown, f"role={role} has capabilities unknown to frontend: {unknown}"


def test_superuser_elevation_caps_exist_in_union():
    """_capabilities_for 對 superuser 追加的能力也必須是合法 Capability。"""
    from unittest.mock import MagicMock

    from app.api.v1.endpoints.experience import _capabilities_for

    union = _parse_frontend_capability_union()
    user = MagicMock()
    user.role = "viewer"
    user.is_superuser = True
    caps = set(_capabilities_for(user))
    assert caps <= union
    assert {"system_ops", "governance", "admin_home"} <= caps


def test_workspace_task_entries_are_filtered_by_runtime_access():
    from app.api.v1.endpoints.experience import _filter_task_workspace_entries

    entries = [
        {"label": "新人訓練", "path": "/job/tasks/training"},
        {"label": "訪談建卡", "path": "/job/tasks/interview"},
        {"label": "師傅經驗", "path": "/knowhow"},
        {"label": "設備維修", "path": "/forms/equipment_repair"},
    ]

    assert _filter_task_workspace_entries(entries, {"training"}) == [
        entries[0], entries[2], entries[3]
    ]


def test_bootstrap_response_contract_keys():
    """bootstrap 回應頂層鍵快照 — 重構時不得誤刪前端依賴的區塊。"""
    from unittest.mock import MagicMock, patch

    from app.api.v1.endpoints.experience import experience_bootstrap

    db = MagicMock()
    user = MagicMock()
    user.id = "00000000-0000-0000-0000-000000000001"
    user.email = "a@b.c"
    user.full_name = "Admin"
    user.role = "owner"
    user.tenant_id = "00000000-0000-0000-0000-000000000002"
    user.is_superuser = False
    user.department_id = None
    with patch(
        "app.services.deployment_mode.resolve_runtime_profiles",
        return_value={"main": {"provider": "ollama"}},
    ):
        data = experience_bootstrap(db=db, current_user=user)

    expected_top = {
        "product", "user", "capabilities", "default_home", "packs",
        "inference", "features",
        # MKA §5.4
        "job_modules", "workspace_entries", "job_role_assignments",
        "active_job_role", "default_job_home", "interaction_capabilities",
    }
    assert expected_top <= set(data.keys()), (
        f"bootstrap contract regression: missing {sorted(expected_top - set(data.keys()))}"
    )
    assert data["default_home"] == "overview"
    assert "field_work" in data["capabilities"]


def test_default_home_field_work_landing():
    """非 admin 的現場角色預設首頁應為 job（與前端 defaultHomePath 一致）。"""
    from unittest.mock import MagicMock, patch

    from app.api.v1.endpoints.experience import experience_bootstrap

    db = MagicMock()
    user = MagicMock()
    user.id = "00000000-0000-0000-0000-000000000003"
    user.email = "e@b.c"
    user.full_name = "Emp"
    user.role = "employee"
    user.tenant_id = "00000000-0000-0000-0000-000000000002"
    user.is_superuser = False
    user.department_id = None
    with patch(
        "app.services.deployment_mode.resolve_runtime_profiles",
        return_value={"main": {"provider": "ollama"}},
    ):
        data = experience_bootstrap(db=db, current_user=user)
    assert data["default_home"] == "job"
