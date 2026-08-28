#!/usr/bin/env python3
"""Run one command-driven P5 degradation drill in isolated staging.

The plan contains argv arrays, not shell strings. The probe command must assert
the expected degraded contract and exit zero. The verify command must print a
JSON object proving that no data was lost and no job was falsely completed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.capacity_gate import load_capacity_spec


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _argv(value: Any, name: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item for item in value)
    ):
        raise ValueError(f"commands.{name} must be a non-empty argv array")
    return value


def _run(argv: list[str], timeout: int) -> dict[str, Any]:
    started = datetime.now(UTC)
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=os.environ.copy(),
        )
        return {
            "argv": argv,
            "started_at": started.isoformat(),
            "completed_at": datetime.now(UTC).isoformat(),
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "argv": argv,
            "started_at": started.isoformat(),
            "completed_at": datetime.now(UTC).isoformat(),
            "exit_code": -1,
            "stdout": "",
            "stderr": str(exc),
        }


def execute_plan(
    plan: dict[str, Any], *, timeout: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    scenario = str(plan.get("scenario") or "")
    required = set(load_capacity_spec()["required_degradation_scenarios"])
    if scenario not in required:
        raise ValueError(f"unsupported degradation scenario: {scenario}")
    commands = plan.get("commands")
    if not isinstance(commands, dict):
        raise TypeError("commands must be an object")
    argv = {
        name: _argv(commands.get(name), name)
        for name in ("baseline", "inject", "probe", "recover", "verify")
    }
    transcript: dict[str, Any] = {
        "schema_version": 1,
        "scenario": scenario,
        "started_at": datetime.now(UTC).isoformat(),
        "steps": {},
    }
    for name in ("baseline", "inject", "probe"):
        transcript["steps"][name] = _run(argv[name], timeout)
        if transcript["steps"][name]["exit_code"] != 0:
            break
    # Recovery is mandatory and is attempted even if injection or probing fails.
    transcript["steps"]["recover"] = _run(argv["recover"], timeout)
    transcript["steps"]["verify"] = _run(argv["verify"], timeout)
    transcript["completed_at"] = datetime.now(UTC).isoformat()
    verify_payload: dict[str, Any] = {}
    try:
        verify_payload = json.loads(transcript["steps"]["verify"]["stdout"])
    except (json.JSONDecodeError, TypeError):
        pass
    required_steps = ("baseline", "inject", "probe", "recover", "verify")
    passed = (
        all(
            transcript["steps"].get(name, {}).get("exit_code") == 0
            for name in required_steps
        )
        and verify_payload.get("data_loss") == 0
        and verify_payload.get("false_completion") == 0
    )
    report = {
        "scenario": scenario,
        "status": "PASS" if passed else "FAIL",
        "execution_class": "live",
        "started_at": transcript["started_at"],
        "completed_at": transcript["completed_at"],
        "data_loss": verify_payload.get("data_loss", -1),
        "false_completion": verify_payload.get("false_completion", -1),
        "verification": verify_payload,
    }
    return report, transcript


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--confirm-isolated-staging", action="store_true")
    args = parser.parse_args()
    if not args.confirm_isolated_staging:
        parser.error("--confirm-isolated-staging is required")
    try:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        report, transcript = execute_plan(plan, timeout=args.timeout_seconds)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    transcript_path = args.output.with_suffix(".raw.json")
    transcript_path.write_text(
        json.dumps(transcript, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report["artifact_sha256"] = _sha256(transcript_path)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 8


if __name__ == "__main__":
    raise SystemExit(main())
