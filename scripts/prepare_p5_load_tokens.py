#!/usr/bin/env python3
"""Attach signed staging-only access tokens to a P5 credential pool.

Run this inside the isolated staging backend container.  It avoids turning the
edge authentication throttle into the ramp-up bottleneck while a dedicated
Locust user continues to exercise live authentication at a safe rate.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models.user import User
from app.services.rls import apply_rls_context


def _read_credentials(path: Path) -> list[dict[str, str]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or not value:
        raise ValueError("credential pool must be a non-empty JSON list")
    rows: list[dict[str, str]] = []
    for index, row in enumerate(value):
        if not isinstance(row, dict) or not row.get("email") or not row.get("password"):
            raise ValueError(f"credential row {index} is incomplete")
        rows.append({"email": str(row["email"]), "password": str(row["password"])})
    return rows


def attach_tokens(
    credentials: list[dict[str, str]],
    *,
    tenant_id: UUID,
    active_emails: set[str],
) -> list[dict[str, str]]:
    missing = sorted({row["email"] for row in credentials} - active_emails)
    if missing:
        preview = ", ".join(missing[:3])
        raise ValueError(f"credential users are not active in tenant: {preview}")
    return [
        {
            **row,
            "access_token": create_access_token(
                row["email"],
                expires_delta=timedelta(hours=96),
                tenant_id=tenant_id,
                additional_claims={"p5_load_test": True},
            ),
        }
        for row in credentials
    ]


def _active_tenant_emails(tenant_id: UUID) -> set[str]:
    with SessionLocal() as db:
        apply_rls_context(db, tenant_id)
        users = (
            db.query(User.email)
            .filter(User.tenant_id == tenant_id, User.status == "active")
            .all()
        )
    return {str(row[0]) for row in users}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument("--confirm-isolated-staging", action="store_true")
    args = parser.parse_args()
    if not args.confirm_isolated_staging:
        parser.error("--confirm-isolated-staging is required")
    if os.getenv("APP_ENV", "").lower() != "staging":
        parser.error("P5 load tokens may only be prepared in APP_ENV=staging")
    try:
        credentials = _read_credentials(args.credentials)
        enriched = attach_tokens(
            credentials,
            tenant_id=args.tenant_id,
            active_emails=_active_tenant_emails(args.tenant_id),
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(enriched, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.chmod(args.output, 0o600)
    print(json.dumps({"tenant_id": str(args.tenant_id), "users": len(enriched)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
