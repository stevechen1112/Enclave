"""CLI preflight for Enclave deployment profiles."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Enclave deployment preflight")
    parser.add_argument("--profile", default="standard", choices=["lite", "standard", "enterprise"])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    from app.services.deployment import DeploymentProfile, run_preflight

    result = run_preflight(DeploymentProfile(args.profile))
    payload = {
        "passed": result.passed,
        "profile": args.profile,
        "checks": result.checks,
        "errors": result.errors,
        "warnings": result.warnings,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"profile={args.profile} passed={result.passed}")
        for c in result.checks:
            print(f"  [{c.get('status', '?')}] {c.get('name')}: {c.get('detail', '')}")
        for w in result.warnings:
            print(f"  WARN: {w}")
        for e in result.errors:
            print(f"  ERR: {e}")
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
