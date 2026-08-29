from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.config import settings
from tests.conftest import create_tenant, create_user, login_user


async def _capture_users(client: AsyncClient, superuser_headers: dict):
    marker = uuid4().hex[:8]
    tenant = await create_tenant(
        client,
        superuser_headers,
        {"name": f"Input I3 {marker}", "plan": "enterprise"},
    )
    identities = [
        (f"owner-{marker}@example.invalid", "Owner123!", "owner"),
        (f"admin-{marker}@example.invalid", "Admin123!", "admin"),
    ]
    for email, password, role in identities:
        await create_user(
            client,
            superuser_headers,
            {
                "email": email,
                "password": password,
                "full_name": role,
                "role": role,
                "tenant_id": tenant["id"],
            },
        )
    return [
        await login_user(client, email, password)
        for email, password, _role in identities
    ]


@pytest.mark.asyncio
async def test_capture_policy_and_session_are_core_governed(
    client: AsyncClient,
    superuser_headers: dict,
    monkeypatch,
):
    monkeypatch.setattr(settings, "LONG_INTERVIEW_MAX_SECONDS", 2700)
    owner, _admin = await _capture_users(client, superuser_headers)

    updated = await client.put(
        "/api/v1/knowledge/captures/policy",
        headers=owner,
        json={"capture_max_duration_seconds": 1200, "audio_retention_days": 30},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["max_duration_seconds"] == 1200

    policy = await client.get("/api/v1/knowledge/captures/policy", headers=owner)
    assert policy.status_code == 200, policy.text
    assert policy.json()["max_duration_seconds"] == 1200
    assert policy.json()["consent_version"] == "core-capture-v1"
    assert len(policy.json()["terminology_sha256"]) == 64
    assert policy.json()["device_limitations"]

    denied = await client.post(
        "/api/v1/knowledge/captures",
        headers=owner,
        json={"title": "未同意", "consent": False},
    )
    assert denied.status_code == 400

    created = await client.post(
        "/api/v1/knowledge/captures",
        headers=owner,
        json={
            "title": "CNC 夜班交接",
            "consent": True,
            "source_module": "core",
            "purpose": "shift_handover",
            "data_classification": "restricted",
            "context_metadata": {
                "site": "一廠",
                "production_line": "A 線",
                "equipment": "CNC-01",
                "tags": ["交接", "異常"],
            },
        },
    )
    assert created.status_code == 200, created.text
    payload = created.json()
    assert payload["source_asset_id"]
    assert payload["capture_metadata"] == {
        "source_module": "core",
        "purpose": "shift_handover",
        "department_id": None,
        "data_classification": "restricted",
        "context_metadata": {
            "site": "一廠",
            "production_line": "A 線",
            "equipment": "CNC-01",
            "tags": ["交接", "異常"],
        },
    }
    assert payload["policy"]["max_duration_seconds"] == 1200
    assert payload["policy"]["terminology_count"] >= 0

    asset = await client.get(
        f"/api/v1/knowledge/assets/{payload['source_asset_id']}", headers=owner
    )
    assert asset.status_code == 200, asset.text
    assert asset.json()["asset_kind"] == "audio"
    assert asset.json()["data_classification"] == "restricted"
    assert asset.json()["metadata"]["source_module"] == "core"
    assert asset.json()["metadata"]["intake_context"]["equipment"] == "CNC-01"


@pytest.mark.asyncio
async def test_capture_session_is_owner_scoped_and_context_fails_closed(
    client: AsyncClient,
    superuser_headers: dict,
):
    owner, same_tenant_admin = await _capture_users(client, superuser_headers)
    invalid = await client.post(
        "/api/v1/knowledge/captures",
        headers=owner,
        json={
            "title": "不合法脈絡",
            "consent": True,
            "context_metadata": {"customer_secret": "must not pass"},
        },
    )
    assert invalid.status_code == 400

    created = await client.post(
        "/api/v1/knowledge/captures",
        headers=owner,
        json={"title": "只限建立者", "consent": True},
    )
    assert created.status_code == 200, created.text
    session_id = created.json()["id"]
    hidden = await client.get(
        f"/api/v1/knowledge/captures/{session_id}", headers=same_tenant_admin
    )
    assert hidden.status_code == 404


def test_frontend_capture_implementation_has_no_mka_dependency():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    platform = root / "frontend" / "src" / "platform" / "input"
    implementation = "\n".join(
        path.read_text(encoding="utf-8")
        for path in platform.glob("*.ts*")
    )
    assert "components/mka" not in implementation
    assert "services/mka" not in implementation
    adapter = (
        root
        / "frontend"
        / "src"
        / "components"
        / "mka"
        / "LongInterviewRecorder.tsx"
    ).read_text(encoding="utf-8")
    assert "platform/input/CoreAudioRecorder" in adapter
