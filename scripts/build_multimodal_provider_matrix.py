#!/usr/bin/env python3
"""Combine independently generated P3 reports into one provider matrix gate."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.eval.multimodal_quality import aggregate_matrix, load_json


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("reports", nargs="+")
    parser.add_argument("--profile", default="configs/eval_profiles/p3_multimodal.yaml")
    parser.add_argument("--require-internal-replay", action="store_true")
    parser.add_argument("--output", default="artifacts/quality/p3_provider_matrix.json")
    args = parser.parse_args()
    profile = yaml.safe_load((ROOT / args.profile).read_text(encoding="utf-8"))
    required = list(profile.get("required_modes") or [])
    if args.require_internal_replay:
        required.append("internal_replay")
    reports = [load_json(ROOT / path) for path in args.reports]
    matrix = aggregate_matrix(reports, required)
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(matrix, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": matrix["status"], "missing_modes": matrix["missing_modes"]}, ensure_ascii=False))
    return 0 if matrix["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
