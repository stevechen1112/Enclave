#!/usr/bin/env python3
"""Assemble existing P5 artifacts and evaluate them without inventing results."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.capacity_gate import (
    capacity_spec_sha256,
    evaluate_p5_capacity_evidence,
    load_capacity_spec,
)


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"artifact must contain a JSON object: {path}")
    return value


def assemble_evidence(
    *,
    capacity_reports: list[dict[str, Any]],
    soak_report: dict[str, Any],
    cost_report: dict[str, Any],
    degradation_reports: list[dict[str, Any]],
    environment: dict[str, Any],
    operator: str,
) -> dict[str, Any]:
    spec = load_capacity_spec()
    return {
        "schema_version": 1,
        "gate": "P5-CAPACITY",
        "capacity_spec_sha256": capacity_spec_sha256(spec),
        "environment": environment,
        "capacity_reports": capacity_reports,
        "soak_test": soak_report,
        "cost_guardrails": cost_report,
        "degradation_tests": degradation_reports,
        "operator": operator,
        "completed_at": datetime.now(UTC).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capacity-report", type=Path, action="append", required=True)
    parser.add_argument("--soak-report", type=Path, required=True)
    parser.add_argument("--cost-report", type=Path, required=True)
    parser.add_argument(
        "--degradation-report", type=Path, action="append", required=True
    )
    parser.add_argument("--environment-evidence", type=Path, required=True)
    parser.add_argument("--operator", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--confirm-isolated-staging", action="store_true")
    args = parser.parse_args()
    if not args.confirm_isolated_staging:
        parser.error("--confirm-isolated-staging is required")
    try:
        environment = _read_object(args.environment_evidence)
        evidence = assemble_evidence(
            capacity_reports=[_read_object(path) for path in args.capacity_report],
            soak_report=_read_object(args.soak_report),
            cost_report=_read_object(args.cost_report),
            degradation_reports=[
                _read_object(path) for path in args.degradation_report
            ],
            environment=environment,
            operator=args.operator,
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    evaluation = evaluate_p5_capacity_evidence(evidence)
    output = {**evidence, "evaluation": evaluation}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(evaluation, ensure_ascii=False, indent=2))
    return 0 if evaluation["status"] == "PASS" else 7


if __name__ == "__main__":
    raise SystemExit(main())
