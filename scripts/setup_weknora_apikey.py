"""A4 — provision a long-lived WeKnora tenant API key for Enclave.

Creates a full-access tenant API key via POST /tenants/{id}/api-keys and writes
it to .env as WEKNORA_API_KEY (prefixed sk-). Unlike the 24h JWT, this machine
credential does not expire until explicitly revoked, so it is the preferred
credential for the gateway's WeKnora adapter.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"

BASE = os.getenv("WEKNORA_BASE_URL", "http://localhost:8081").rstrip("/")
EMAIL = os.getenv("WEKNORA_ADMIN_EMAIL", "enclave@enclave.local")
PASSWORD = os.getenv("WEKNORA_ADMIN_PASSWORD", "Enclave2024!")
KEY_NAME = os.getenv("WEKNORA_API_KEY_NAME", "enclave-gateway")


def _upsert_env(key: str, value: str) -> None:
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    pattern = re.compile(rf"^{re.escape(key)}=")
    out, replaced = [], False
    for line in lines:
        if pattern.match(line):
            out.append(f"{key}={value}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")


def main() -> int:
    api = f"{BASE}/api/v1"
    with httpx.Client(timeout=30) as client:
        login = client.post(f"{api}/auth/login", json={"email": EMAIL, "password": PASSWORD})
        if login.status_code != 200:
            print(f"login failed: {login.status_code} {login.text[:200]}")
            return 1
        body = login.json()
        token = body.get("token")
        tenant = body.get("active_tenant") or {}
        tenant_id = tenant.get("id") or (body.get("user") or {}).get("tenant_id")
        if not token or not tenant_id:
            print(f"missing token/tenant: token={bool(token)} tenant_id={tenant_id}")
            return 1
        print(f"logged in; tenant_id={tenant_id}")

        headers = {"Authorization": f"Bearer {token}"}
        # Reuse an existing key with the same name if present (idempotent).
        existing = client.get(f"{api}/tenants/{tenant_id}/api-keys", headers=headers)
        if existing.status_code == 200:
            for k in (existing.json().get("data") or []):
                if k.get("name") == KEY_NAME and not k.get("revoked_at"):
                    print(f"key '{KEY_NAME}' already exists (id={k.get('id')}); "
                          "plaintext is not recoverable — delete it first to rotate.")
                    return 0

        resp = client.post(
            f"{api}/tenants/{tenant_id}/api-keys",
            headers=headers,
            json={"name": KEY_NAME, "full_access": True},
        )
        if resp.status_code not in (200, 201):
            print(f"create api key failed: {resp.status_code} {resp.text[:300]}")
            return 1
        data = resp.json().get("data") or resp.json()
        token_value = data.get("token") or data.get("api_key")
        if not token_value:
            print(f"no token in response: {str(data)[:300]}")
            return 1

    _upsert_env("WEKNORA_API_KEY", token_value)
    print(f"written WEKNORA_API_KEY to .env (len={len(token_value)}, "
          f"prefix={token_value[:3]}...)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
