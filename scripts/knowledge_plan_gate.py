#!/usr/bin/env python3
"""Fast, deterministic gates for the knowledge enhancement mainline."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default="artifacts/knowledge/plan_gate_last_run.json")
    args = ap.parse_args()
    tests = [
        "tests/test_knowledge_engine.py",
        "tests/test_knowledge_control.py",
        "tests/test_query_plan.py",
        "tests/test_source_verifier.py",
        "tests/test_scan_parse_delivery.py",
        "tests/test_fusion_policy.py",
    ]
    proc = subprocess.run([sys.executable, "-m", "pytest", *tests, "-q"], cwd=ROOT, text=True, capture_output=True)
    result = {"schema_version": 1, "gate": "KB-CORE", "generated_at": datetime.now(timezone.utc).isoformat(),
              "status": "PASS" if proc.returncode == 0 else "FAIL", "tests": tests,
              "returncode": proc.returncode, "output_tail": (proc.stdout + proc.stderr)[-12000:]}
    out = ROOT / args.output; out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(result["status"]); print(result["output_tail"])
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
