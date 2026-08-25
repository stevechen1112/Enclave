"""Compatibility entry point: seed all six synthetic Demo personas safely."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db.session import SessionLocal
from app.services.demo_tenant import seed_demo_tenant, verify_demo_tenant


def main() -> None:
    db = SessionLocal()
    try:
        seed_demo_tenant(db)
        db.commit()
        result = verify_demo_tenant(db)
        if not result["ok"]:
            raise SystemExit(f"Demo verification failed: {result['checks']}")
        print(f"Synthetic Demo ready: tenant_id={result['tenant_id']}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
