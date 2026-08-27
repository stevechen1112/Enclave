"""Generate a signed all-active-tenant report; never removes a route or data."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.session import MaintenanceSessionLocal
from app.services.legacy_retirement import build_signed_removal_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-eligible", action="store_true")
    args = parser.parse_args()
    signing_key = os.getenv("LEGACY_REMOVAL_REPORT_KEY", "")
    if len(signing_key) < 32:
        print(
            "LEGACY_REMOVAL_REPORT_KEY (>=32 characters) is required", file=sys.stderr
        )
        return 2
    with MaintenanceSessionLocal() as db:
        report = build_signed_removal_report(db, signing_key=signing_key)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"status={report['status']} tenants={report['active_tenant_count']} output={args.output}"
    )
    if args.require_eligible and not report["removal_eligible"]:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
