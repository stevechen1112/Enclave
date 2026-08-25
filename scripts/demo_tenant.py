"""Seed, verify, or transactionally reset the isolated synthetic Demo tenant."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from app.db.session import SessionLocal
from app.demo.manifest import DEMO_TENANT_ID
from app.services.demo_tenant import (
    reset_demo_tenant,
    seed_demo_tenant,
    verify_demo_tenant,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("seed", "verify", "reset"))
    parser.add_argument(
        "--confirm-reset",
        help="Reset requires the exact canonical Demo tenant UUID.",
    )
    args = parser.parse_args()
    if args.action == "reset" and args.confirm_reset != str(DEMO_TENANT_ID):
        parser.error(f"reset requires --confirm-reset {DEMO_TENANT_ID}")

    db = SessionLocal()
    try:
        if args.action == "verify":
            result = verify_demo_tenant(db)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 1
        result = reset_demo_tenant(db) if args.action == "reset" else seed_demo_tenant(db)
        db.flush()
        verification = verify_demo_tenant(db)
        if not verification["ok"]:
            raise RuntimeError(f"Demo verification failed: {verification['checks']}")
        db.commit()
        print(
            json.dumps(
                {"operation": result, "verification": verification},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if verification["ok"] else 1
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
