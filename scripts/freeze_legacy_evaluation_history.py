#!/usr/bin/env python3
"""Freeze Z3/Z4 first-run inputs/results as hash-only historical evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    "testdata/golden/z3_blind_questions.yaml",
    "testdata/golden/z4_blind_questions.yaml",
    "artifacts/blind_z3/eval_z3_run.json",
    "artifacts/blind_z4/eval_z4_run.json",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="artifacts/knowledge/legacy_eval_freeze.json")
    args = parser.parse_args()
    output = ROOT / args.output
    current = {name: _sha(ROOT / name) for name in FILES if (ROOT / name).is_file()}
    if len(current) != len(FILES):
        missing = sorted(set(FILES) - set(current))
        raise SystemExit("missing legacy evaluation evidence: " + ", ".join(missing))

    if output.exists():
        frozen = json.loads(output.read_text(encoding="utf-8"))
        status = "PASS" if frozen.get("files") == current else "FAIL"
        print(status)
        return 0 if status == "PASS" else 1

    payload = {
        "schema_version": 1,
        "gate": "KB-BL-LEGACY-EVAL",
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "classification": "opened_holdouts_regression_only",
        "privacy": "paths_and_sha256_only",
        "files": current,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
