"""A3 — Service token lifecycle for sidecar JWTs.

PipesHub and WeKnora issue 24-hour JWTs. Storing them statically in .env means the
integration silently dies 24h after bootstrap (the root cause of the 401 outages).
This module provides a self-refreshing token source:

  - decodes the JWT `exp` and refreshes proactively before expiry
  - re-authenticates with stored credentials when the token is expired/absent
  - falls back to the static env token only when no credentials are configured

The provider is async-safe and caches the token in-process. Adapters call
``get_token()`` instead of reading a static string.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

# Refresh this many seconds before the JWT actually expires.
REFRESH_MARGIN_S = 300


def _decode_exp(token: str) -> Optional[int]:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return int(json.loads(base64.urlsafe_b64decode(payload)).get("exp"))
    except Exception:
        return None


class ServiceTokenProvider:
    """Base class: caches a JWT and refreshes it before expiry."""

    def __init__(self) -> None:
        self._token: Optional[str] = None
        self._exp: int = 0
        self._lock = asyncio.Lock()

    def _needs_refresh(self) -> bool:
        if not self._token:
            return True
        return int(time.time()) >= (self._exp - REFRESH_MARGIN_S)

    def _set_token(self, token: str) -> str:
        self._token = token
        self._exp = _decode_exp(token) or (int(time.time()) + 3600)
        return token

    async def get_token(self) -> str:
        if not self._needs_refresh():
            return self._token  # type: ignore[return-value]
        async with self._lock:
            # Re-check inside the lock: another coroutine may have refreshed.
            if not self._needs_refresh():
                return self._token  # type: ignore[return-value]
            token = await self._authenticate()
            logger.info("%s: refreshed service token (exp=%s)",
                        type(self).__name__, self._exp)
            return token

    async def _authenticate(self) -> str:
        raise NotImplementedError


class StaticTokenProvider(ServiceTokenProvider):
    """Wraps a fixed token (e.g. a non-expiring API key). Never refreshes."""

    def __init__(self, token: str) -> None:
        super().__init__()
        self._set_token(token)
        # Static tokens are treated as non-expiring unless they carry an exp.
        if _decode_exp(token) is None:
            self._exp = 2 ** 31

    async def _authenticate(self) -> str:  # pragma: no cover - never called
        return self._token  # type: ignore[return-value]


class PipesHubTokenProvider(ServiceTokenProvider):
    """Re-authenticates against PipesHub initAuth + authenticate."""

    def __init__(self, base_url: str, email: str, password: str) -> None:
        super().__init__()
        self.base_url = base_url.rstrip("/") + "/api/v1"
        self.email = email
        self.password = password

    async def _authenticate(self) -> str:
        async with httpx.AsyncClient(timeout=60) as client:
            init = await client.post(
                f"{self.base_url}/userAccount/initAuth", json={"email": self.email}
            )
            session = init.headers.get("x-session-token")
            if not session:
                raise RuntimeError(f"pipeshub initAuth no session: {init.status_code}")
            auth = await client.post(
                f"{self.base_url}/userAccount/authenticate",
                headers={"x-session-token": session},
                json={"method": "password",
                      "credentials": {"password": self.password},
                      "email": self.email},
            )
            token = (auth.json() or {}).get("accessToken")
            if not token:
                raise RuntimeError(f"pipeshub authenticate failed: {auth.status_code}")
            return self._set_token(token)


class WeKnoraTokenProvider(ServiceTokenProvider):
    """Re-authenticates against WeKnora /auth/login."""

    def __init__(self, base_url: str, email: str, password: str) -> None:
        super().__init__()
        self.base_url = base_url.rstrip("/") + "/api/v1"
        self.email = email
        self.password = password

    async def _authenticate(self) -> str:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self.base_url}/auth/login",
                json={"email": self.email, "password": self.password},
            )
            token = (resp.json() or {}).get("token")
            if not token:
                raise RuntimeError(f"weknora login failed: {resp.status_code}")
            return self._set_token(token)


# ---------------------------------------------------------------------------
# Factory: build the right provider from environment.
# ---------------------------------------------------------------------------

def build_pipeshub_token_provider() -> ServiceTokenProvider:
    """Prefer credential-based auto-refresh; fall back to the static env JWT."""
    base = os.getenv("PIPESHUB_BASE_URL", "http://localhost:8012")
    email = os.getenv("PIPESHUB_ADMIN_EMAIL", "")
    password = os.getenv("PIPESHUB_ADMIN_PASSWORD", "")
    if email and password:
        return PipesHubTokenProvider(base, email, password)
    static = os.getenv("PIPESHUB_API_KEY", "")
    logger.warning("PIPESHUB_ADMIN_EMAIL/PASSWORD unset; using static JWT "
                   "(will expire in 24h). Set credentials to enable auto-refresh.")
    return StaticTokenProvider(static)


def build_weknora_token_provider() -> ServiceTokenProvider:
    base = os.getenv("WEKNORA_BASE_URL", "http://localhost:8081")
    # A4: a long-lived sk- tenant API key is the preferred machine credential —
    # it never expires, so no refresh login is needed.
    static = os.getenv("WEKNORA_API_KEY", "")
    if static.startswith("sk-"):
        return StaticTokenProvider(static)
    email = os.getenv("WEKNORA_ADMIN_EMAIL", "")
    password = os.getenv("WEKNORA_ADMIN_PASSWORD", "")
    if email and password:
        return WeKnoraTokenProvider(base, email, password)
    logger.warning("WEKNORA_API_KEY is a 24h JWT and no admin credentials are set; "
                   "run scripts/setup_weknora_apikey.py to provision a long-lived sk- key.")
    return StaticTokenProvider(static)
