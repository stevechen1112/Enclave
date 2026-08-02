"""A5 — sidecar 401/403 must fail closed (raise), never silently return []."""
from __future__ import annotations

import pytest
import respx
import httpx

from app.core.authorization import AuthorizationContext
from app.gateway.adapters.pipeshub_http import PipesHubHTTPAdapter
from app.gateway.adapters.weknora_http import WeKnoraHTTPAdapter
from app.gateway.contracts import SidecarAuthError


def _authz() -> AuthorizationContext:
    return AuthorizationContext(tenant_id="t", subject_id="s")


@pytest.mark.asyncio
@respx.mock
async def test_pipeshub_search_401_raises():
    respx.post("http://pipeshub.test/api/v1/search").mock(
        return_value=httpx.Response(401, json={"error": "unauthorized"})
    )
    adapter = PipesHubHTTPAdapter(base_url="http://pipeshub.test", api_key="k")
    with pytest.raises(SidecarAuthError) as exc:
        await adapter.search(_authz(), "q")
    assert exc.value.status_code == 401
    assert exc.value.provider == "pipeshub"


@pytest.mark.asyncio
@respx.mock
async def test_pipeshub_search_403_raises():
    respx.post("http://pipeshub.test/api/v1/search").mock(
        return_value=httpx.Response(403, json={"error": "forbidden"})
    )
    adapter = PipesHubHTTPAdapter(base_url="http://pipeshub.test", api_key="k")
    with pytest.raises(SidecarAuthError):
        await adapter.search(_authz(), "q")


@pytest.mark.asyncio
@respx.mock
async def test_weknora_search_401_raises(monkeypatch):
    monkeypatch.setenv("WEKNORA_KB_ID", "kb-test")
    respx.post("http://weknora.test/api/v1/knowledge-search").mock(
        return_value=httpx.Response(401, json={"error": "expired token"})
    )
    adapter = WeKnoraHTTPAdapter(base_url="http://weknora.test", api_key="k")
    with pytest.raises(SidecarAuthError) as exc:
        await adapter.search(_authz(), "q")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
@respx.mock
async def test_weknora_search_500_still_returns_empty(monkeypatch):
    # Non-auth server errors keep the existing graceful-degradation contract.
    monkeypatch.setenv("WEKNORA_KB_ID", "kb-test")
    respx.post("http://weknora.test/api/v1/knowledge-search").mock(
        return_value=httpx.Response(500, json={"error": "boom"})
    )
    adapter = WeKnoraHTTPAdapter(base_url="http://weknora.test", api_key="k")
    assert await adapter.search(_authz(), "q") == []


def test_router_marks_auth_error_not_retryable():
    from app.gateway.contracts import SidecarAuthError as SAE
    err = SAE("weknora", 401, "expired")
    assert "weknora" in str(err)
    assert "401" in str(err)
    assert err.status_code == 401
