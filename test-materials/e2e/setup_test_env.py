#!/usr/bin/env python3
"""Create and verify the canonical synthetic E2E Demo tenant."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.session import SessionLocal
from app.services.demo_tenant import seed_demo_tenant, verify_demo_tenant


def main() -> int:
    db = SessionLocal()
    try:
        operation = seed_demo_tenant(db)
        db.flush()
        verification = verify_demo_tenant(db)
        if not verification["ok"]:
            db.rollback()
            print(json.dumps(verification, ensure_ascii=False, indent=2))
            return 1
        db.commit()
        print(
            json.dumps(
                {"operation": operation, "verification": verification},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
