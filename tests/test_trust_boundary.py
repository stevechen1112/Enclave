"""Trust boundary + service token HTTP tests."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.gateway.service_auth import mint_service_token, verify_service_token
from app.main import app as fastapi_app
from app.middleware.trust_boundary import TrustBoundaryMiddleware


@pytest.mark.asyncio
async def test_trust_boundary_strips_forged_enclave_headers():
    captured = {}

    async def _capture(scope, receive, send):
        if scope["type"] == "http":
            headers = {
                k.decode("latin-1").lower(): v.decode("latin-1")
                for k, v in scope.get("headers", [])
            }
            captured["headers"] = headers
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

    wrapped = TrustBoundaryMiddleware(_capture)
    transport = ASGITransport(app=wrapped)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/probe",
            headers={
                "X-Enclave-Caller": "forged",
                "X-Enclave-Service-Token": "forged-token",
                "X-Service-Role": "admin",
                "X-Custom": "keep-me",
            },
        )
    assert resp.status_code == 200
    headers = captured["headers"]
    assert "x-enclave-caller" not in headers
    assert "x-enclave-service-token" not in headers
    assert "x-service-role" not in headers
    assert headers.get("x-custom") == "keep-me"


@pytest.mark.asyncio
async def test_internal_service_echo_requires_valid_token(client: AsyncClient):
    # missing token
    r = await client.post("/api/v1/internal/service-echo", json={"message": "hi"})
    assert r.status_code == 401

    # forged token via Authorization（Edge 會剝離 X-Enclave-*，回呼必須走 Bearer）
    r2 = await client.post(
        "/api/v1/internal/service-echo",
        json={"message": "hi", "audience": "enclave-callback"},
        headers={"Authorization": "Bearer v1.enclave-callback.x.9999999999.deadbeef"},
    )
    assert r2.status_code == 401

    # valid token via Authorization Bearer
    token = mint_service_token(audience="enclave-callback", ttl_seconds=60)
    assert verify_service_token(token, "enclave-callback")
    r3 = await client.post(
        "/api/v1/internal/service-echo",
        json={"message": "hi", "audience": "enclave-callback"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r3.status_code == 200
    assert r3.json()["verified"] is True

    # X-Enclave-Service-Token 經 Edge 剝離後不得單獨作為信任依據
    r4 = await client.post(
        "/api/v1/internal/service-echo",
        json={"message": "hi", "audience": "enclave-callback"},
        headers={"X-Enclave-Service-Token": token},
    )
    assert r4.status_code == 401


def test_wrong_audience_rejected():
    token = mint_service_token(audience="ragflow", ttl_seconds=60)
    assert verify_service_token(token, "ragflow")
    assert not verify_service_token(token, "pipeshub")
