#!/usr/bin/env python3
"""Run one provenance-bound P5 degradation drill in isolated staging.

Every step must use a version-controlled driver under
``scripts/p5_degradation_drivers``. The plan pins the driver hash and the
runner binds the resulting evidence to measured environment, release, tenant,
scenario and recovery observations. Arbitrary shell snippets cannot create a
P5 PASS artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
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


def _committed_driver_sha256(file_value: str, source_commit: str) -> str:
    try:
        result = subprocess.run(
            ["git", "show", f"{source_commit}:{file_value}"],
            cwd=ROOT,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("could not inspect the committed degradation driver") from exc
    if result.returncode != 0:
        raise ValueError("driver is not present in the plan source_commit")
    try:
        diff = subprocess.run(
            ["git", "diff", "--quiet", source_commit, "--", file_value],
            cwd=ROOT,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("could not compare the degradation driver") from exc
    if diff.returncode != 0:
        raise ValueError("working driver differs from the plan source_commit")
    return hashlib.sha256(result.stdout).hexdigest()


def _command(
    value: Any, name: str, scenario: str, source_commit: str
) -> list[str]:
    if not isinstance(value, dict):
        raise TypeError(f"commands.{name} must be an object")
    argv = _argv(value.get("argv"), f"{name}.argv")
    driver_value = value.get("driver")
    driver_hash = value.get("driver_sha256")
    if not isinstance(driver_value, str) or not driver_value:
        raise ValueError(f"commands.{name}.driver is required")
    if not isinstance(driver_hash, str) or len(driver_hash) != 64:
        raise ValueError(f"commands.{name}.driver_sha256 is invalid")
    driver_relative = Path(driver_value)
    if driver_relative.is_absolute():
        raise ValueError(f"commands.{name}.driver must be repository-relative")
    driver = (ROOT / driver_relative).resolve()
    driver_root = (ROOT / "scripts" / "p5_degradation_drivers").resolve()
    try:
        driver.relative_to(driver_root)
    except ValueError as exc:
        raise ValueError(
            f"commands.{name}.driver must be under scripts/p5_degradation_drivers"
        ) from exc
    if not driver.is_file():
        raise ValueError(f"commands.{name}.driver does not exist")
    if _committed_driver_sha256(driver_value, source_commit) != driver_hash:
        raise ValueError(f"commands.{name}.driver_sha256 does not match source_commit")
    trusted_files = value.get("trusted_files")
    if not isinstance(trusted_files, list) or not trusted_files:
        raise ValueError(f"commands.{name}.trusted_files must be a non-empty array")
    trusted_by_repo_path: dict[str, Path] = {}
    for index, trusted in enumerate(trusted_files):
        if not isinstance(trusted, dict):
            raise TypeError(f"commands.{name}.trusted_files[{index}] must be an object")
        repo_path = str(trusted.get("repo_path") or "")
        expected_hash = str(trusted.get("sha256") or "")
        relative = Path(repo_path)
        if not repo_path or relative.is_absolute():
            raise ValueError(f"commands.{name}.trusted_files[{index}] path is invalid")
        resolved = (ROOT / relative).resolve()
        try:
            resolved.relative_to((ROOT / "scripts").resolve())
        except ValueError as exc:
            raise ValueError(
                f"commands.{name}.trusted_files[{index}] must be under scripts"
            ) from exc
        if not resolved.is_file():
            raise ValueError(f"commands.{name}.trusted_files[{index}] does not exist")
        if _committed_driver_sha256(repo_path, source_commit) != expected_hash:
            raise ValueError(
                f"commands.{name}.trusted_files[{index}] does not match source_commit"
            )
        trusted_by_repo_path[repo_path] = resolved
    integrity_path = "scripts/run_p5_integrity_probe.py"
    if integrity_path not in trusted_by_repo_path:
        raise ValueError(f"commands.{name} must pin {integrity_path}")
    try:
        integrity_index = argv.index("--integrity-script")
        configured_integrity = Path(argv[integrity_index + 1])
    except (ValueError, IndexError) as exc:
        raise ValueError(f"commands.{name}.argv requires --integrity-script") from exc
    if not configured_integrity.is_absolute():
        configured_integrity = ROOT / configured_integrity
    if configured_integrity.resolve() != trusted_by_repo_path[integrity_path]:
        raise ValueError(f"commands.{name}.argv integrity script is not the pinned file")
    sensitive_flags = ("password", "secret", "token", "api-key", "authorization")
    if any(
        item.startswith("-")
        and any(secret in item.lower() for secret in sensitive_flags)
        for item in argv
    ):
        raise ValueError(
            f"commands.{name}.argv contains a sensitive flag; use environment variables"
        )
    resolved_argv_paths = set()
    for item in argv:
        if item.startswith("-"):
            continue
        try:
            candidate = Path(item)
            if not candidate.is_absolute():
                candidate = ROOT / candidate
            resolved_argv_paths.add(candidate.resolve())
        except OSError:
            continue
    if driver not in resolved_argv_paths:
        raise ValueError(f"commands.{name}.argv must execute its pinned driver")
    expected = {
        "--p5-scenario": scenario,
        "--p5-step": name,
    }
    for flag, expected_value in expected.items():
        try:
            index = argv.index(flag)
            actual = argv[index + 1]
        except (ValueError, IndexError) as exc:
            raise ValueError(f"commands.{name}.argv requires {flag}") from exc
        if actual != expected_value:
            raise ValueError(f"commands.{name}.argv has invalid {flag}")
    return argv


def _validate_environment(
    environment: dict[str, Any], *, source_commit: str, compose_project: str
) -> None:
    if environment.get("status") != "PASS":
        raise ValueError("environment evidence is not PASS")
    if environment.get("isolated_staging") is not True:
        raise ValueError("environment evidence is not isolated staging")
    if environment.get("co_resident_enclave_projects"):
        raise ValueError("environment evidence contains co-resident Enclave projects")
    if environment.get("source_commit") != source_commit:
        raise ValueError("environment source_commit mismatch")
    if environment.get("compose_project") != compose_project:
        raise ValueError("environment compose_project mismatch")
    if len(str(environment.get("artifact_sha256") or "")) != 64:
        raise ValueError("environment artifact hash is missing")


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
    plan: dict[str, Any], *, timeout: int, environment: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(plan, dict):
        raise TypeError("plan must be a JSON object")
    if plan.get("schema_version") != 1:
        raise ValueError("plan schema_version must be 1")
    scenario = str(plan.get("scenario") or "")
    required = set(load_capacity_spec()["required_degradation_scenarios"])
    if scenario not in required:
        raise ValueError(f"unsupported degradation scenario: {scenario}")
    source_commit = str(plan.get("source_commit") or "")
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("plan source_commit must be a full lowercase git SHA")
    compose_project = str(plan.get("compose_project") or "")
    if not compose_project:
        raise ValueError("plan compose_project is required")
    _validate_environment(
        environment,
        source_commit=source_commit,
        compose_project=compose_project,
    )
    commands = plan.get("commands")
    if not isinstance(commands, dict):
        raise TypeError("commands must be an object")
    argv = {
        name: _command(commands.get(name), name, scenario, source_commit)
        for name in ("baseline", "inject", "probe", "recover", "verify")
    }
    transcript: dict[str, Any] = {
        "schema_version": 1,
        "scenario": scenario,
        "source_commit": source_commit,
        "compose_project": compose_project,
        "environment_artifact_sha256": environment["artifact_sha256"],
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
        and verify_payload.get("cross_tenant_leak") == 0
        and verify_payload.get("recovered") is True
        and verify_payload.get("schema_version") == 1
        and verify_payload.get("scenario") == scenario
        and verify_payload.get("source_commit") == source_commit
        and bool(str(verify_payload.get("tenant_id") or "").strip())
        and isinstance(verify_payload.get("observations"), list)
        and bool(verify_payload["observations"])
    )
    report = {
        "scenario": scenario,
        "status": "PASS" if passed else "FAIL",
        "execution_class": "live",
        "source_commit": source_commit,
        "compose_project": compose_project,
        "environment_artifact_sha256": environment["artifact_sha256"],
        "started_at": transcript["started_at"],
        "completed_at": transcript["completed_at"],
        "data_loss": verify_payload.get("data_loss", -1),
        "false_completion": verify_payload.get("false_completion", -1),
        "cross_tenant_leak": verify_payload.get("cross_tenant_leak", -1),
        "recovered": verify_payload.get("recovered", False),
        "tenant_id": verify_payload.get("tenant_id", ""),
        "verification": verify_payload,
    }
    return report, transcript


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--environment-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--confirm-isolated-staging", action="store_true")
    args = parser.parse_args()
    if not args.confirm_isolated_staging:
        parser.error("--confirm-isolated-staging is required")
    try:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        environment = json.loads(
            args.environment_evidence.read_text(encoding="utf-8")
        )
        if not isinstance(environment, dict):
            raise TypeError("environment evidence must be a JSON object")
        environment["artifact_sha256"] = _sha256(args.environment_evidence)
        report, transcript = execute_plan(
            plan,
            timeout=args.timeout_seconds,
            environment=environment,
        )
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
