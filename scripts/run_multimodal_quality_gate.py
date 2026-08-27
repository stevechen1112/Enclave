#!/usr/bin/env python3
"""Run the P3 per-slice multimodal provider quality matrix."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.eval.multimodal_quality import (
    Thresholds,
    build_contract_results,
    evaluate,
    load_json,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="configs/eval_profiles/p3_multimodal.yaml")
    parser.add_argument("--mode", choices=("mock_contract", "internal_replay", "degraded"), required=True)
    parser.add_argument("--results", help="Provider output bundle; mandatory for internal_replay")
    parser.add_argument("--provider", default="enclave.contract-fixture")
    parser.add_argument("--provider-version", default="1")
    parser.add_argument("--output")
    args = parser.parse_args()

    profile_path = ROOT / args.profile
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    manifest = load_json(ROOT / profile["corpus_manifest"])
    thresholds = Thresholds.from_dict(profile.get("thresholds"))
    if args.mode == "internal_replay":
        if not args.results:
            parser.error("--results is mandatory for internal_replay; live evidence is never synthesized")
        bundle = load_json(ROOT / args.results)
        if bundle.get("mode") != "internal_replay":
            parser.error("internal replay bundle must declare mode=internal_replay")
    else:
        bundle = build_contract_results(manifest, args.mode, args.provider, args.provider_version)

    report = evaluate(manifest, bundle, thresholds)
    report["generated_at"] = datetime.now(timezone.utc).isoformat()
    report["profile"] = profile.get("name")
    report["profile_version"] = str(profile.get("version"))
    output = Path(args.output) if args.output else Path(profile.get("artifact_dir", "artifacts/quality")) / f"p3_{args.mode}.json"
    output = output if output.is_absolute() else ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "mode": args.mode, "output": str(output)}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
