#!/usr/bin/env python3
"""Read-only local tenant diagnostic.

Remote host access and direct SQL mutations were deliberately removed. Run this
inside the target application container so it uses that deployment's normal
DATABASE_URL and ORM model.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.session import SessionLocal
from app.models.tenant import Tenant


def main() -> int:
    db = SessionLocal()
    try:
        rows = db.query(Tenant).order_by(Tenant.name.asc()).all()
        result = [
            {
                "id": str(tenant.id),
                "name": tenant.name,
                "status": tenant.status,
                "is_demo": bool(tenant.is_demo),
            }
            for tenant in rows
        ]
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
