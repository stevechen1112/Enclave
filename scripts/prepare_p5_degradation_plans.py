#!/usr/bin/env python3
"""Generate provenance-bound command plans for all P5 degradation scenarios."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.capacity_gate import load_capacity_spec

DRIVER = Path("scripts/p5_degradation_drivers/live_drill.py")
INTEGRITY_PROBE = Path("scripts/run_p5_integrity_probe.py")


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON artifact must be an object: {path}")
    return value


def _committed_hash(source_commit: str, path: Path = DRIVER) -> str:
    result = subprocess.run(
        ["git", "show", f"{source_commit}:{path.as_posix()}"],
        cwd=ROOT,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError(f"trusted file is not committed at source_commit: {path}")
    diff = subprocess.run(
        ["git", "diff", "--quiet", source_commit, "--", path.as_posix()],
        cwd=ROOT,
        timeout=30,
        check=False,
    )
    if diff.returncode != 0:
        raise ValueError(f"working trusted file differs from source_commit: {path}")
    return hashlib.sha256(result.stdout).hexdigest()


def build_plans(
    *,
    environment: dict[str, Any],
    output_dir: Path,
    python_executable: str,
    base_url: str,
    tenant_id: str,
    email: str,
    fixture: Path,
    credentials: Path,
    grounding_evidence: Path,
    provider_service: str,
    sidecar_key: str,
    sidecar_service: str,
) -> list[Path]:
    source_commit = str(environment.get("source_commit") or "")
    compose_project = str(environment.get("compose_project") or "")
    if (
        environment.get("status") != "PASS"
        or environment.get("isolated_staging") is not True
        or environment.get("co_resident_enclave_projects")
    ):
        raise ValueError("environment evidence is not isolated-staging PASS")
    if len(source_commit) != 40 or not compose_project:
        raise ValueError("environment release binding is incomplete")
    driver_hash = _committed_hash(source_commit, DRIVER)
    integrity_hash = _committed_hash(source_commit, INTEGRITY_PROBE)
    output_dir.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    for scenario in load_capacity_spec()["required_degradation_scenarios"]:
        common = [
            python_executable,
            str((ROOT / DRIVER).resolve()),
            "--p5-scenario",
            scenario,
            "--source-commit",
            source_commit,
            "--compose-project",
            compose_project,
            "--base-url",
            base_url.rstrip("/"),
            "--tenant-id",
            tenant_id,
            "--email",
            email,
            "--state-file",
            str((output_dir / f"{scenario}.state.json").resolve()),
            "--fixture",
            str(fixture.resolve()),
            "--credentials",
            str(credentials.resolve()),
            "--grounding-evidence",
            str(grounding_evidence.resolve()),
            "--integrity-script",
            str((ROOT / INTEGRITY_PROBE).resolve()),
            "--provider-service",
            provider_service,
            "--sidecar-key",
            sidecar_key,
            "--sidecar-service",
            sidecar_service,
        ]
        commands = {}
        for step in ("baseline", "inject", "probe", "recover", "verify"):
            commands[step] = {
                "argv": [*common, "--p5-step", step],
                "driver": DRIVER.as_posix(),
                "driver_sha256": driver_hash,
                "trusted_files": [
                    {
                        "repo_path": INTEGRITY_PROBE.as_posix(),
                        "sha256": integrity_hash,
                    }
                ],
            }
        plan = {
            "schema_version": 1,
            "scenario": scenario,
            "source_commit": source_commit,
            "compose_project": compose_project,
            "environment_artifact_sha256": environment.get("artifact_sha256"),
            "commands": commands,
        }
        path = output_dir / f"{scenario}.plan.json"
        path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        created.append(path)
    return created


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment-evidence", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--python-executable", default=sys.executable)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--grounding-evidence", type=Path, required=True)
    parser.add_argument("--provider-service", default="ollama-embed")
    parser.add_argument(
        "--sidecar-key",
        choices=("ragflow", "pipeshub", "weknora"),
        default="ragflow",
    )
    parser.add_argument("--sidecar-service", default="ragflow")
    args = parser.parse_args()
    try:
        environment = _object(args.environment_evidence)
        environment["artifact_sha256"] = hashlib.sha256(
            args.environment_evidence.read_bytes()
        ).hexdigest()
        required = (args.fixture, args.credentials, args.grounding_evidence)
        if not all(path.is_file() for path in required):
            raise ValueError("fixture, credentials and grounding evidence must exist")
        paths = build_plans(
            environment=environment,
            output_dir=args.output_dir,
            python_executable=args.python_executable,
            base_url=args.base_url,
            tenant_id=args.tenant_id,
            email=args.email,
            fixture=args.fixture,
            credentials=args.credentials,
            grounding_evidence=args.grounding_evidence,
            provider_service=args.provider_service,
            sidecar_key=args.sidecar_key,
            sidecar_service=args.sidecar_service,
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        parser.error(str(exc))
    print(json.dumps({"status": "PASS", "plans": [str(path) for path in paths]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
