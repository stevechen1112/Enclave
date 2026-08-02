"""A4 — WeKnora sk- machine credential uses X-API-Key, not Bearer JWT."""
from __future__ import annotations

import os

import pytest

from app.gateway.adapters.weknora_http import WeKnoraHTTPAdapter
from app.gateway.token_provider import (
    StaticTokenProvider,
    WeKnoraTokenProvider,
    build_weknora_token_provider,
)


def test_apply_credential_routes_sk_to_x_api_key():
    adapter = WeKnoraHTTPAdapter(api_key="sk-testkey")
    headers = {"Authorization": "Bearer sk-testkey", "Content-Type": "application/json"}
    out = adapter._apply_credential(headers, "sk-testkey")
    assert out["X-API-Key"] == "sk-testkey"
    assert "Authorization" not in out


def test_apply_credential_leaves_jwt_as_bearer():
    adapter = WeKnoraHTTPAdapter(api_key="eyJhbGciOiJI.payload.sig")
    headers = {"Authorization": "Bearer eyJhbGciOiJI.payload.sig"}
    out = adapter._apply_credential(headers, "eyJhbGciOiJI.payload.sig")
    assert "X-API-Key" not in out
    assert out["Authorization"].startswith("Bearer eyJ")


@pytest.mark.asyncio
async def test_headers_emit_x_api_key_for_sk():
    adapter = WeKnoraHTTPAdapter(
        api_key="sk-abc",
        token_provider=StaticTokenProvider("sk-abc"),
    )
    h = await adapter._headers()
    assert h["X-API-Key"] == "sk-abc"
    assert "Authorization" not in h or not h.get("Authorization", "").startswith("Bearer sk-")


def test_factory_prefers_sk_over_login(monkeypatch):
    monkeypatch.setenv("WEKNORA_API_KEY", "sk-machine-key")
    monkeypatch.setenv("WEKNORA_ADMIN_EMAIL", "a@b.c")
    monkeypatch.setenv("WEKNORA_ADMIN_PASSWORD", "secret")
    prov = build_weknora_token_provider()
    assert isinstance(prov, StaticTokenProvider)


def test_factory_falls_back_to_login_for_jwt(monkeypatch):
    monkeypatch.setenv("WEKNORA_API_KEY", "eyJhbGciOiJI.payload.sig")
    monkeypatch.setenv("WEKNORA_ADMIN_EMAIL", "a@b.c")
    monkeypatch.setenv("WEKNORA_ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("WEKNORA_BASE_URL", "http://weknora.test")
    prov = build_weknora_token_provider()
    assert isinstance(prov, WeKnoraTokenProvider)
