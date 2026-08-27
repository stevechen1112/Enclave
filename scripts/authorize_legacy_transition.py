"""Verify evidence for one lifecycle transition; never edits the registry."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.legacy_retirement import evaluate_stage_transition
from app.services.rollback_gate import evaluate_rollback_evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--surface", required=True)
    parser.add_argument(
        "--current", choices=("observe", "warn", "disable"), required=True
    )
    parser.add_argument(
        "--target", choices=("warn", "disable", "remove"), required=True
    )
    parser.add_argument("--tenant-notice-acknowledged", action="store_true")
    parser.add_argument("--rollback-evidence", type=Path)
    args = parser.parse_args()
    key = os.getenv("LEGACY_REMOVAL_REPORT_KEY", "")
    if len(key) < 32 or not args.report.is_file():
        print(
            "valid report and LEGACY_REMOVAL_REPORT_KEY are required", file=sys.stderr
        )
        return 2
    report = json.loads(args.report.read_text(encoding="utf-8"))
    rollback = None
    if args.rollback_evidence is not None and args.rollback_evidence.is_file():
        rollback = evaluate_rollback_evidence(
            json.loads(args.rollback_evidence.read_text(encoding="utf-8"))
        )
    result = evaluate_stage_transition(
        surface_key=args.surface,
        current_stage=args.current,
        target_stage=args.target,
        report=report,
        signing_key=key,
        tenant_notice_acknowledged=args.tenant_notice_acknowledged,
        rollback_result=rollback,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
