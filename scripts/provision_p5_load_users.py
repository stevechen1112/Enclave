#!/usr/bin/env python3
"""Provision isolated-staging users for a P5 Locust credential pool."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import httpx


def _object(response: httpx.Response) -> dict[str, Any]:
    value = response.json()
    if not isinstance(value, dict):
        raise TypeError("API response is not a JSON object")
    return value


def provision(
    *,
    base_url: str,
    admin_email: str,
    admin_password: str,
    user_password: str,
    count: int,
    prefix: str,
    timeout: int,
) -> tuple[str, list[dict[str, str]]]:
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout) as client:
        login = client.post(
            "/api/v1/auth/login/access-token",
            data={"username": admin_email, "password": admin_password},
        )
        login.raise_for_status()
        token = _object(login).get("access_token")
        if not token:
            raise ValueError("admin login did not return a token")
        headers = {"Authorization": f"Bearer {token}"}
        me = client.get("/api/v1/users/me", headers=headers)
        me.raise_for_status()
        tenant_id = str(_object(me).get("tenant_id") or "")
        if not tenant_id:
            raise ValueError("admin account has no tenant")
        quota_url = f"/api/v1/admin/tenants/{tenant_id}/quota"
        quota_response = client.get(quota_url, headers=headers)
        quota_response.raise_for_status()
        quota = _object(quota_response)
        required_limit = int(quota.get("current_users", 0) or 0) + count
        configured_limit = quota.get("max_users")
        if configured_limit is not None and int(configured_limit) < required_limit:
            update = client.put(
                quota_url,
                headers=headers,
                json={"max_users": required_limit},
            )
            update.raise_for_status()
        credentials = []
        for index in range(count):
            email = f"{prefix}-{index:04d}@enclave.invalid"
            invited = client.post(
                "/api/v1/admin/users/invite",
                headers=headers,
                json={
                    "email": email,
                    "full_name": f"P5 Load User {index:04d}",
                    "password": user_password,
                    "role": "owner",
                },
            )
            invited.raise_for_status()
            credentials.append({"email": email, "password": user_password})
        return tenant_id, credentials


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--admin-email", required=True)
    parser.add_argument("--admin-password-env", default="P5_ADMIN_PASSWORD")
    parser.add_argument("--user-password-env", default="P5_LOAD_USER_PASSWORD")
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=60)
    parser.add_argument("--confirm-isolated-staging", action="store_true")
    args = parser.parse_args()
    if not args.confirm_isolated_staging:
        parser.error("--confirm-isolated-staging is required")
    if args.count <= 0 or args.count > 5000:
        parser.error("count must be between 1 and 5000")
    admin_password = os.getenv(args.admin_password_env, "")
    user_password = os.getenv(args.user_password_env, "")
    if not admin_password or not user_password:
        parser.error("admin and load-user passwords must be injected")
    try:
        tenant_id, credentials = provision(
            base_url=args.base_url,
            admin_email=args.admin_email,
            admin_password=admin_password,
            user_password=user_password,
            count=args.count,
            prefix=args.prefix,
            timeout=args.timeout_seconds,
        )
    except (TypeError, ValueError, httpx.HTTPError) as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(credentials, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.chmod(args.output, 0o600)
    print(json.dumps({"tenant_id": tenant_id, "users": len(credentials)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
