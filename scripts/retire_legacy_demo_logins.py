#!/usr/bin/env python3
"""Audit or disable the retired shared-account Demo identities.

Rows are preserved for historical foreign-key ownership. Disablement only makes
the five old persona users inactive and rotates their password hashes. A platform
superuser match is always refused and requires a separate security incident flow.
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy.orm import Session

from app.core.security import get_password_hash
from app.db.session import MaintenanceSessionLocal
from app.models.user import User
from app.services.rls import apply_rls_bypass

LEGACY_DEMO_EMAILS = frozenset(
    {
        "sales@demo.mka",
        "field@demo.mka",
        "master@demo.mka",
        "newcomer@demo.mka",
        "viewer@demo.mka",
    }
)
CONFIRM_DISABLE = "retire-legacy-demo-logins"


def audit_legacy_demo_logins(db: Session) -> list[dict[str, object]]:
    apply_rls_bypass(
        db,
        actor_identity="operator:retire_legacy_demo_logins",
        operation="audit_legacy_demo_logins",
        reason="Inspect allowlisted retired demo identities",
    )
    rows = db.query(User).filter(User.email.in_(LEGACY_DEMO_EMAILS)).all()
    return [
        {
            "id": str(user.id),
            "tenant_id": str(user.tenant_id),
            "email": user.email,
            "status": user.status,
            "role": user.role,
            "is_superuser": bool(user.is_superuser),
        }
        for user in sorted(rows, key=lambda item: item.email)
    ]


def disable_legacy_demo_logins(db: Session) -> list[dict[str, object]]:
    apply_rls_bypass(
        db,
        actor_identity="operator:retire_legacy_demo_logins",
        operation="disable_legacy_demo_logins",
        reason="Disable allowlisted retired demo identities after explicit confirmation",
    )
    rows = db.query(User).filter(User.email.in_(LEGACY_DEMO_EMAILS)).all()
    if any(user.is_superuser for user in rows):
        raise RuntimeError("refusing to modify a platform superuser")
    if not rows:
        return []
    for user in rows:
        user.status = "inactive"
        user.hashed_password = get_password_hash(secrets.token_urlsafe(48))
    db.flush()
    return audit_legacy_demo_logins(db)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("audit", "disable"))
    parser.add_argument("--confirm-disable", default="")
    args = parser.parse_args()
    if args.action == "disable" and args.confirm_disable != CONFIRM_DISABLE:
        parser.error(f"disable requires --confirm-disable {CONFIRM_DISABLE}")

    db = MaintenanceSessionLocal()
    try:
        result = (
            disable_legacy_demo_logins(db)
            if args.action == "disable"
            else audit_legacy_demo_logins(db)
        )
        if args.action == "disable":
            db.commit()
        print(json.dumps({"action": args.action, "users": result}, indent=2))
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
