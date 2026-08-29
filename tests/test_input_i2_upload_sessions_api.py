from __future__ import annotations

import hashlib
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.config import settings
from app.services.storage import reset_storage_backend
from tests.conftest import create_tenant, create_user, login_user


async def _users(client: AsyncClient, superuser_headers: dict):
    marker = uuid4().hex[:8]
    tenant = await create_tenant(client, superuser_headers, {"name": f"Input I2 {marker}", "plan": "enterprise"})
    other = await create_tenant(client, superuser_headers, {"name": f"Input I2 Other {marker}", "plan": "enterprise"})
    identities = [
        (f"owner-{marker}@example.invalid", "Owner123!", "owner", tenant["id"]),
        (f"admin-{marker}@example.invalid", "Admin123!", "admin", tenant["id"]),
        (f"other-{marker}@example.invalid", "Other123!", "owner", other["id"]),
    ]
    for email, password, role, tenant_id in identities:
        await create_user(client, superuser_headers, {
            "email": email, "password": password, "full_name": role, "role": role, "tenant_id": tenant_id,
        })
    return [await login_user(client, email, password) for email, password, _role, _tenant in identities]


@pytest.fixture
def small_parts(tmp_path, monkeypatch):
    reset_storage_backend()
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "local")
    monkeypatch.setattr(settings, "UPLOAD_SESSION_PART_SIZE", 4)
    monkeypatch.setattr(settings, "UPLOAD_SESSION_MIN_PART_SIZE", 4)
    monkeypatch.setattr(settings, "UPLOAD_SESSION_MAX_PART_SIZE", 16)
    monkeypatch.setattr(settings, "CLAMAV_ENABLED", False)
    yield
    reset_storage_backend()


def _session_payload(key: str, size: int = 10):
    return {
        "filename": "procedure.txt",
        "media_type": "text/plain",
        "byte_size": size,
        "part_size": 4,
        "idempotency_key": key,
        "data_classification": "internal",
        "context_metadata": {"site": "一廠", "equipment": "CNC-01"},
    }


@pytest.mark.asyncio
async def test_out_of_order_duplicate_resume_and_commit_are_lossless(
    client: AsyncClient, superuser_headers: dict, small_parts, monkeypatch
):
    from app.api import ingestion_guard
    from app.api.v1.endpoints import documents as documents_endpoint

    monkeypatch.setattr(documents_endpoint.process_document_task, "delay", lambda **_kwargs: None)
    monkeypatch.setattr(ingestion_guard, "enforce_ingestion_queue_capacity", lambda: None)
    owner, _admin, _other = await _users(client, superuser_headers)
    created = await client.post("/api/v1/knowledge/upload-sessions", headers=owner, json=_session_payload("resume-1"))
    assert created.status_code == 201, created.text
    session_id = created.json()["id"]
    chunks = {1: b"abcd", 2: b"efgh", 3: b"ij"}
    for number in (3, 1):
        chunk = chunks[number]
        response = await client.put(
            f"/api/v1/knowledge/upload-sessions/{session_id}/parts/{number}",
            headers={**owner, "X-Part-SHA256": hashlib.sha256(chunk).hexdigest()},
            content=chunk,
        )
        assert response.status_code == 200, response.text

    resumed = await client.get(f"/api/v1/knowledge/upload-sessions/{session_id}", headers=owner)
    assert [part["part_number"] for part in resumed.json()["acknowledged_parts"]] == [1, 3]
    duplicate = await client.put(
        f"/api/v1/knowledge/upload-sessions/{session_id}/parts/1",
        headers={**owner, "X-Part-SHA256": hashlib.sha256(chunks[1]).hexdigest()},
        content=chunks[1],
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["received_parts"] == 2

    chunk = chunks[2]
    assert (await client.put(
        f"/api/v1/knowledge/upload-sessions/{session_id}/parts/2",
        headers={**owner, "X-Part-SHA256": hashlib.sha256(chunk).hexdigest()}, content=chunk,
    )).status_code == 200
    committed = await client.post(f"/api/v1/knowledge/upload-sessions/{session_id}/commit", headers=owner, json={})
    assert committed.status_code == 200, committed.text
    assert committed.json()["content_sha256"] == hashlib.sha256(b"abcdefghij").hexdigest()
    replay = await client.post(f"/api/v1/knowledge/upload-sessions/{session_id}/commit", headers=owner, json={})
    assert replay.status_code == 200
    assert replay.json()["id"] == committed.json()["id"]


@pytest.mark.asyncio
async def test_checksum_corruption_missing_parts_and_conflicting_duplicate_fail_closed(
    client: AsyncClient, superuser_headers: dict, small_parts
):
    owner, _admin, _other = await _users(client, superuser_headers)
    created = await client.post("/api/v1/knowledge/upload-sessions", headers=owner, json=_session_payload("fault-1"))
    session_id = created.json()["id"]
    corrupt = await client.put(
        f"/api/v1/knowledge/upload-sessions/{session_id}/parts/1",
        headers={**owner, "X-Part-SHA256": hashlib.sha256(b"xxxx").hexdigest()}, content=b"abcd",
    )
    assert corrupt.status_code == 422
    assert (await client.get(f"/api/v1/knowledge/upload-sessions/{session_id}", headers=owner)).json()["received_parts"] == 0
    missing = await client.post(f"/api/v1/knowledge/upload-sessions/{session_id}/commit", headers=owner, json={})
    assert missing.status_code == 409

    good = hashlib.sha256(b"abcd").hexdigest()
    assert (await client.put(
        f"/api/v1/knowledge/upload-sessions/{session_id}/parts/1",
        headers={**owner, "X-Part-SHA256": good}, content=b"abcd",
    )).status_code == 200
    conflict = await client.put(
        f"/api/v1/knowledge/upload-sessions/{session_id}/parts/1",
        headers={**owner, "X-Part-SHA256": hashlib.sha256(b"wxyz").hexdigest()}, content=b"wxyz",
    )
    assert conflict.status_code == 409


@pytest.mark.asyncio
async def test_session_is_hidden_from_other_users_and_other_tenants(
    client: AsyncClient, superuser_headers: dict, small_parts
):
    owner, same_tenant_admin, other_tenant_owner = await _users(client, superuser_headers)
    created = await client.post("/api/v1/knowledge/upload-sessions", headers=owner, json=_session_payload("isolation-1"))
    session_id = created.json()["id"]
    for outsider in (same_tenant_admin, other_tenant_owner):
        assert (await client.get(f"/api/v1/knowledge/upload-sessions/{session_id}", headers=outsider)).status_code == 404
        assert (await client.delete(f"/api/v1/knowledge/upload-sessions/{session_id}", headers=outsider)).status_code == 404


@pytest.mark.asyncio
async def test_init_is_idempotent_but_rejects_identity_change(
    client: AsyncClient, superuser_headers: dict, small_parts
):
    owner, _admin, _other = await _users(client, superuser_headers)
    first = await client.post("/api/v1/knowledge/upload-sessions", headers=owner, json=_session_payload("init-idempotent"))
    replay = await client.post("/api/v1/knowledge/upload-sessions", headers=owner, json=_session_payload("init-idempotent"))
    assert replay.json()["id"] == first.json()["id"]
    changed = _session_payload("init-idempotent", size=11)
    assert (await client.post("/api/v1/knowledge/upload-sessions", headers=owner, json=changed)).status_code == 409


@pytest.mark.asyncio
async def test_expired_session_cleans_staging_and_rejects_more_parts(
    client: AsyncClient, superuser_headers: dict, small_parts, monkeypatch
):
    owner, _admin, _other = await _users(client, superuser_headers)
    monkeypatch.setattr(settings, "UPLOAD_SESSION_TTL_HOURS", 0)
    created = await client.post(
        "/api/v1/knowledge/upload-sessions",
        headers=owner,
        json=_session_payload("expired-1"),
    )
    session_id = created.json()["id"]
    state = await client.get(
        f"/api/v1/knowledge/upload-sessions/{session_id}", headers=owner
    )
    assert state.status_code == 200
    assert state.json()["status"] == "expired"
    part = b"abcd"
    rejected = await client.put(
        f"/api/v1/knowledge/upload-sessions/{session_id}/parts/1",
        headers={**owner, "X-Part-SHA256": hashlib.sha256(part).hexdigest()},
        content=part,
    )
    assert rejected.status_code == 410


@pytest.mark.asyncio
async def test_large_file_uses_multiple_production_sized_parts_end_to_end(
    client: AsyncClient, superuser_headers: dict, small_parts, monkeypatch
):
    from app.api import ingestion_guard
    from app.api.v1.endpoints import documents as documents_endpoint

    monkeypatch.setattr(settings, "UPLOAD_SESSION_PART_SIZE", 5 * 1024 * 1024)
    monkeypatch.setattr(settings, "UPLOAD_SESSION_MIN_PART_SIZE", 5 * 1024 * 1024)
    monkeypatch.setattr(settings, "UPLOAD_SESSION_MAX_PART_SIZE", 16 * 1024 * 1024)
    monkeypatch.setattr(documents_endpoint.process_document_task, "delay", lambda **_kwargs: None)
    monkeypatch.setattr(ingestion_guard, "enforce_ingestion_queue_capacity", lambda: None)
    owner, _admin, _other = await _users(client, superuser_headers)
    content = (b"production-line-check\n" * 550_000) + b"end"
    part_size = 5 * 1024 * 1024
    payload = _session_payload("large-file-1", size=len(content))
    payload["part_size"] = part_size
    created = await client.post(
        "/api/v1/knowledge/upload-sessions", headers=owner, json=payload
    )
    assert created.status_code == 201, created.text
    state = created.json()
    assert state["total_parts"] >= 2
    for number in range(1, state["total_parts"] + 1):
        chunk = content[(number - 1) * part_size : number * part_size]
        response = await client.put(
            f"/api/v1/knowledge/upload-sessions/{state['id']}/parts/{number}",
            headers={**owner, "X-Part-SHA256": hashlib.sha256(chunk).hexdigest()},
            content=chunk,
        )
        assert response.status_code == 200, response.text
    committed = await client.post(
        f"/api/v1/knowledge/upload-sessions/{state['id']}/commit",
        headers=owner,
        json={"expected_sha256": hashlib.sha256(content).hexdigest()},
    )
    assert committed.status_code == 200, committed.text
    assert committed.json()["content_sha256"] == hashlib.sha256(content).hexdigest()
