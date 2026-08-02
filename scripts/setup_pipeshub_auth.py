"""Bootstrap PipesHub org (if needed) and obtain JWT for Enclave .env."""
from __future__ import annotations

import json
import re
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
DEFAULT_BASE = "http://localhost:8012"
ADMIN_EMAIL = "admin@enclave.local"
ADMIN_PASSWORD = "Enclave123!"
ADMIN_NAME = "Enclave Admin"
ORG_SHORT = "Enclave"


def _load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def _upsert_env(key: str, value: str) -> None:
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    pattern = re.compile(rf"^{re.escape(key)}=")
    replaced = False
    out: list[str] = []
    for line in lines:
        if pattern.match(line):
            out.append(f"{key}={value}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")


def bootstrap_and_login(base_url: str) -> str:
    api = base_url.rstrip("/") + "/api/v1"
    with httpx.Client(timeout=60) as client:
        exists = client.get(f"{api}/org/exists").json()
        if not exists.get("exists"):
            print("Creating PipesHub organization...")
            resp = client.post(
                f"{api}/org",
                json={
                    "accountType": "business",
                    "shortName": ORG_SHORT,
                    "registeredName": "Enclave Integration Org",
                    "contactEmail": ADMIN_EMAIL,
                    "adminFullName": ADMIN_NAME,
                    "password": ADMIN_PASSWORD,
                },
            )
            if resp.status_code not in (200, 201):
                raise RuntimeError(f"org create failed: {resp.status_code} {resp.text[:300]}")
            print("Organization created.")

        init = client.post(f"{api}/userAccount/initAuth", json={"email": ADMIN_EMAIL})
        session = init.headers.get("x-session-token")
        if not session:
            raise RuntimeError(f"initAuth missing session token: {init.status_code} {init.text[:200]}")

        auth = client.post(
            f"{api}/userAccount/authenticate",
            headers={"x-session-token": session},
            json={"method": "password", "credentials": {"password": ADMIN_PASSWORD}, "email": ADMIN_EMAIL},
        )
        data = auth.json()
        token = data.get("accessToken")
        if not token:
            raise RuntimeError(f"authenticate failed: {auth.status_code} {json.dumps(data)[:300]}")
        return token


def main() -> int:
    env = _load_env()
    base = env.get("PIPESHUB_BASE_URL", DEFAULT_BASE)
    print(f"PipesHub base: {base}")
    token = bootstrap_and_login(base)
    _upsert_env("PIPESHUB_ENABLED", "true")
    _upsert_env("PIPESHUB_BASE_URL", base)
    _upsert_env("PIPESHUB_API_KEY", token)
    print("Updated .env: PIPESHUB_ENABLED=true, PIPESHUB_API_KEY=<jwt>")
    print(f"Login: {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
