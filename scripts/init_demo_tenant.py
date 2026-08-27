"""Idempotently initialize the canonical synthetic Demo when explicitly enabled."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.services.demo_tenant import (  # noqa: E402
    seed_demo_tenant,
    verify_demo_tenant,
)


def main() -> int:
    if not settings.DEMO_LOGIN_ENABLED:
        print(json.dumps({"enabled": False, "operation": "skipped"}))
        return 0

    db = SessionLocal()
    try:
        operation = seed_demo_tenant(db)
        db.flush()
        verification = verify_demo_tenant(db)
        if not verification["ok"]:
            raise RuntimeError(
                f"Demo verification failed: {verification['checks']}"
            )
        db.commit()
        print(
            json.dumps(
                {
                    "enabled": True,
                    "operation": operation,
                    "verification": verification,
                },
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
