#!/usr/bin/env python3
"""Validate, but never manufacture, P4 operational evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.resilience_gate import evaluate_p4_resilience_evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    if not args.evidence.is_file():
        print(f"missing evidence: {args.evidence}", file=sys.stderr)
        return 2
    result = evaluate_p4_resilience_evidence(
        json.loads(args.evidence.read_text(encoding="utf-8"))
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
