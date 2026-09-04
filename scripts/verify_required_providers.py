#!/usr/bin/env python3
"""Run real production-provider calls and fail closed on any unavailable role."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.provider_runtime_health import probe_required_providers  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", help="Optional JSON evidence path")
    parser.add_argument(
        "--allow-unidentified-release",
        action="store_true",
        help="Development only: do not fail when build release identity is absent",
    )
    args = parser.parse_args()
    report = probe_required_providers()
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    print(payload)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload + "\n", encoding="utf-8")
    providers_pass = report["status"] == "pass"
    release_bound = bool(report.get("release_bound"))
    return 0 if providers_pass and (
        release_bound or args.allow_unidentified_release
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
