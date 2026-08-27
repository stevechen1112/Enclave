"""Report legacy usage gates for one tenant; never removes routes or data."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import case, func

from app.db.session import SessionLocal
from app.models.audit import AuditLog
from app.platform.deprecations import SURFACES
from app.services.rls import apply_rls_context


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument(
        "--require-eligible",
        action="store_true",
        help="exit 2 unless every registered surface satisfies its removal gate",
    )
    args = parser.parse_args()
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=30)
    with SessionLocal() as db:
        apply_rls_context(db, args.tenant_id)
        usage = {
            str(key): {"hits_30d": int(count), "last_used_at": last_used}
            for key, count, last_used in (
                db.query(
                    AuditLog.target_id,
                    func.sum(case((AuditLog.created_at >= cutoff, 1), else_=0)),
                    func.max(AuditLog.created_at),
                )
                .filter(
                    AuditLog.tenant_id == args.tenant_id,
                    AuditLog.action == "legacy_surface_used",
                )
                .group_by(AuditLog.target_id)
                .all()
            )
        }
    report = []
    for surface in SURFACES:
        row = usage.get(surface.key, {})
        last_used_at = row.get("last_used_at")
        report.append(
            {
                "key": surface.key,
                "stage": surface.stage,
                "hits_30d": row.get("hits_30d", 0),
                "last_used_at": last_used_at.isoformat() if last_used_at else None,
                "eligible_after": surface.eligible_after.isoformat(),
                "removal_eligible": surface.removal_eligible(
                    last_used_at=last_used_at, now=now
                ),
            }
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.require_eligible and not all(row["removal_eligible"] for row in report):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
