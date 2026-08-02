"""A3 — token provider lifecycle tests."""
from __future__ import annotations

import base64
import json
import time

import pytest

from app.gateway.token_provider import (
    REFRESH_MARGIN_S,
    ServiceTokenProvider,
    StaticTokenProvider,
    _decode_exp,
)


def _jwt(exp: int) -> str:
    def b64(obj) -> str:
        raw = json.dumps(obj).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")
    return f"{b64({'alg': 'HS256', 'typ': 'JWT'})}.{b64({'exp': exp, 'iat': exp - 86400})}.sig"


def test_decode_exp():
    exp = int(time.time()) + 3600
    assert _decode_exp(_jwt(exp)) == exp
    assert _decode_exp("not-a-jwt") is None


def test_static_provider_non_expiring_key_never_refreshes():
    p = StaticTokenProvider("plain-api-key")
    assert p._needs_refresh() is False


def test_static_provider_expiring_jwt_detects_expiry():
    p = StaticTokenProvider(_jwt(int(time.time()) - 10))  # already expired
    assert p._needs_refresh() is True


@pytest.mark.asyncio
async def test_provider_refreshes_when_near_expiry(monkeypatch):
    calls = {"n": 0}

    class Fake(ServiceTokenProvider):
        async def _authenticate(self) -> str:
            calls["n"] += 1
            return self._set_token(_jwt(int(time.time()) + 86400))

    p = Fake()
    # Seed with a token inside the refresh margin.
    p._set_token(_jwt(int(time.time()) + REFRESH_MARGIN_S - 5))
    assert p._needs_refresh() is True
    tok = await p.get_token()
    assert calls["n"] == 1
    assert p._needs_refresh() is False
    # Second call within validity reuses the cache.
    await p.get_token()
    assert calls["n"] == 1
    assert _decode_exp(tok) is not None


@pytest.mark.asyncio
async def test_provider_concurrent_refresh_single_flight():
    import asyncio
    calls = {"n": 0}

    class Slow(ServiceTokenProvider):
        async def _authenticate(self) -> str:
            calls["n"] += 1
            await asyncio.sleep(0.05)
            return self._set_token(_jwt(int(time.time()) + 86400))

    p = Slow()
    results = await asyncio.gather(*(p.get_token() for _ in range(5)))
    assert calls["n"] == 1  # lock prevented stampede
    assert len(set(results)) == 1
