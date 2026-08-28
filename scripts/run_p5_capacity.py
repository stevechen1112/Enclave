#!/usr/bin/env python3
"""Run one isolated live P5 profile test and build a fail-closed report."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.capacity_gate import load_capacity_spec, profile_load_target
from app.services.capacity_report import build_capacity_report
from app.services.hardware_inventory import detect_hardware, hardware_shortfalls


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_post_load_integrity_probe(
    *,
    container: str,
    credentials: Path,
    grounding_evidence: Path,
    output: Path,
    run_started_at: str,
    load_completed_at: str,
    timeout_seconds: int,
) -> int:
    """Execute the integrity probe in the exact backend release under test."""
    if not container or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for char in container):
        raise ValueError("backend container name contains unsupported characters")
    nonce = uuid.uuid4().hex
    remote_credentials = f"/tmp/p5-integrity-{nonce}-credentials.json"
    remote_grounding = f"/tmp/p5-integrity-{nonce}-grounding.json"
    remote_output = f"/tmp/p5-integrity-{nonce}-evidence.json"
    copied: list[str] = []
    try:
        for source, target in (
            (credentials, remote_credentials),
            (grounding_evidence, remote_grounding),
        ):
            result = subprocess.run(
                ["docker", "cp", str(source.resolve()), f"{container}:{target}"],
                check=False,
            )
            if result.returncode != 0:
                return result.returncode
            copied.append(target)
        permission_result = subprocess.run(
            [
                "docker",
                "exec",
                "-u",
                "0",
                container,
                "chown",
                "enclave:enclave",
                remote_credentials,
                remote_grounding,
            ],
            check=False,
        )
        if permission_result.returncode != 0:
            return permission_result.returncode
        permission_result = subprocess.run(
            [
                "docker",
                "exec",
                "-u",
                "0",
                container,
                "chmod",
                "600",
                remote_credentials,
                remote_grounding,
            ],
            check=False,
        )
        if permission_result.returncode != 0:
            return permission_result.returncode
        probe = subprocess.run(
            [
                "docker",
                "exec",
                "-u",
                "enclave",
                container,
                "python",
                "scripts/run_p5_integrity_probe.py",
                "--base-url",
                "http://127.0.0.1:8000",
                "--credentials",
                remote_credentials,
                "--grounding-evidence",
                remote_grounding,
                "--output",
                remote_output,
                "--run-started-at",
                run_started_at,
                "--load-completed-at",
                load_completed_at,
                "--reconciliation-timeout-seconds",
                str(timeout_seconds),
                "--confirm-isolated-staging",
            ],
            check=False,
        )
        copied.append(remote_output)
        copy_result = subprocess.run(
            ["docker", "cp", f"{container}:{remote_output}", str(output.resolve())],
            check=False,
        )
        if copy_result.returncode != 0:
            return copy_result.returncode
        return probe.returncode
    finally:
        if copied:
            subprocess.run(
                ["docker", "exec", "-u", "0", container, "rm", "-f", *copied],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--profile", choices=("lite", "standard", "enterprise"), required=True
    )
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--document-fixture", type=Path, required=True)
    parser.add_argument("--audio-fixture", type=Path, required=True)
    parser.add_argument("--video-fixture", type=Path, required=True)
    parser.add_argument("--grounding-evidence", type=Path, required=True)
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--backend-container", required=True)
    parser.add_argument("--reconciliation-timeout-seconds", type=int, default=1800)
    parser.add_argument("--duration-seconds", type=int, default=900)
    parser.add_argument("--spawn-rate", type=int, default=10)
    parser.add_argument("--telemetry-interval-seconds", type=int, default=60)
    parser.add_argument("--locust-executable", default=sys.executable)
    args = parser.parse_args()
    for path in (
        args.document_fixture,
        args.audio_fixture,
        args.video_fixture,
        args.grounding_evidence,
        args.credentials,
    ):
        if not path.is_file():
            parser.error(f"missing required evidence or fixture: {path}")
    spec = load_capacity_spec()
    grounding = json.loads(args.grounding_evidence.read_text(encoding="utf-8"))
    grounding["artifact_sha256"] = _sha256(args.grounding_evidence)
    grounding_errors = []
    if grounding.get("status") != "PASS" or grounding.get("execution_class") != "live":
        grounding_errors.append("grounding evidence is not a live PASS")
    if grounding.get("publication_class") != "isolated_staging_fixture":
        grounding_errors.append("grounding evidence is not a staging fixture publication")
    if not str(grounding.get("kb_revision_id") or "").strip():
        grounding_errors.append("grounding evidence has no active KB revision")
    if int(grounding.get("search_results", 0) or 0) <= 0:
        grounding_errors.append("grounding evidence has no search results")
    if int(grounding.get("chat_sources", 0) or 0) <= 0:
        grounding_errors.append("grounding evidence has no chat sources")
    if len(str(grounding.get("source_commit") or "")) != 40:
        grounding_errors.append("grounding evidence has no full source commit")
    if not str(grounding.get("tenant_id") or "").strip():
        grounding_errors.append("grounding evidence has no tenant identity")
    if grounding_errors:
        parser.error("; ".join(grounding_errors))
    minimum = int(spec["test_policy"]["capacity_min_duration_seconds"])
    if args.duration_seconds < minimum:
        parser.error(f"formal capacity duration must be at least {minimum} seconds")
    if args.reconciliation_timeout_seconds <= 0:
        parser.error("reconciliation timeout must be positive")
    users = int(profile_load_target(spec, args.profile)["concurrent_users"])
    observed_hardware = detect_hardware(ROOT)
    shortfalls = hardware_shortfalls(
        observed_hardware, spec["profiles"][args.profile]["hardware"]
    )
    if shortfalls:
        parser.error("host does not qualify for profile: " + "; ".join(shortfalls))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    integrity_evidence = args.output_dir / f"{args.profile}_integrity_evidence.json"
    prefix = args.output_dir / args.profile
    telemetry_jsonl = args.output_dir / f"{args.profile}_telemetry.jsonl"
    telemetry_summary = args.output_dir / f"{args.profile}_telemetry_summary.json"
    environment = os.environ.copy()
    environment.update(
        {
            "CAPACITY_PROFILE": args.profile,
            "LOAD_TEST_CLASS": "capacity",
            "LOAD_MULTIPLIER": str(spec["test_policy"]["peak_multiplier"]),
            "P5_FULL_SCENARIO": "true",
            "LOAD_DOCUMENT_FIXTURE_PATH": str(args.document_fixture.resolve()),
            "LOAD_AUDIO_FIXTURE_PATH": str(args.audio_fixture.resolve()),
            "LOAD_VIDEO_FIXTURE_PATH": str(args.video_fixture.resolve()),
            "LOAD_TEST_CREDENTIALS_PATH": str(args.credentials.resolve()),
        }
    )
    missing_secrets = [
        name
        for name in (
            "LOAD_TEST_USER_PASSWORD",
            "LOAD_TEST_ADMIN_PASSWORD",
            "LOAD_TEST_SUPERUSER_PASSWORD",
        )
        if not environment.get(name)
    ]
    if missing_secrets:
        parser.error("missing injected load credentials: " + ", ".join(missing_secrets))
    collector_command = [
        sys.executable,
        str(ROOT / "scripts" / "collect_p5_telemetry.py"),
        "--base-url",
        args.base_url,
        "--output",
        str(telemetry_jsonl),
        "--summary",
        str(telemetry_summary),
        "--duration-seconds",
        str(args.duration_seconds),
        "--interval-seconds",
        str(args.telemetry_interval_seconds),
        "--docker-stats",
    ]
    if int(spec["profiles"][args.profile]["hardware"].get("gpu_vram_gb", 0)) > 0:
        collector_command.append("--gpu-stats")
    locust_command = [
        args.locust_executable,
        "-m",
        "locust",
        "-f",
        str(ROOT / "tests" / "load" / "locustfile.py"),
        "--host",
        args.base_url,
        "--headless",
        "-u",
        str(users),
        "-r",
        str(args.spawn_rate),
        "--run-time",
        f"{args.duration_seconds}s",
        "--csv",
        str(prefix),
        "--csv-full-history",
    ]
    started = datetime.now(UTC)
    with (args.output_dir / f"{args.profile}_collector.log").open(
        "w", encoding="utf-8"
    ) as collector_log:
        collector = subprocess.Popen(
            collector_command,
            cwd=ROOT,
            env=environment,
            stdout=collector_log,
            stderr=subprocess.STDOUT,
        )
        with (args.output_dir / f"{args.profile}_locust.log").open(
            "w", encoding="utf-8"
        ) as locust_log:
            load = subprocess.run(
                locust_command,
                cwd=ROOT,
                env=environment,
                stdout=locust_log,
                stderr=subprocess.STDOUT,
                check=False,
            )
        collector_result = collector.wait(timeout=args.duration_seconds + 180)
    completed = datetime.now(UTC)
    integrity_result = _run_post_load_integrity_probe(
        container=args.backend_container,
        credentials=args.credentials,
        grounding_evidence=args.grounding_evidence,
        output=integrity_evidence,
        run_started_at=started.isoformat(),
        load_completed_at=completed.isoformat(),
        timeout_seconds=args.reconciliation_timeout_seconds,
    )
    if not integrity_evidence.is_file():
        integrity_evidence.write_text(
            json.dumps(
                {
                    "status": "FAIL",
                    "execution_class": "live",
                    "data_corruption": -1,
                    "cross_tenant_leak": -1,
                    "unrecoverable_backlog": -1,
                    "tenant_isolation_status": "FAIL",
                    "job_reconciliation_status": "FAIL",
                    "errors": ["post-load integrity probe did not produce evidence"],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    integrity = json.loads(integrity_evidence.read_text(encoding="utf-8"))
    integrity["artifact_sha256"] = _sha256(integrity_evidence)
    report = build_capacity_report(
        profile_name=args.profile,
        users=users,
        duration_seconds=int((completed - started).total_seconds()),
        started_at=started.isoformat(),
        completed_at=completed.isoformat(),
        locust_stats_path=Path(str(prefix) + "_stats.csv"),
        telemetry_path=telemetry_jsonl,
        integrity=integrity,
        grounding=grounding,
        observed_hardware=observed_hardware,
    )
    report["runner"] = {
        "locust_exit_code": load.returncode,
        "collector_exit_code": collector_result,
        "integrity_probe_exit_code": integrity_result,
    }
    if load.returncode != 0 or collector_result != 0 or integrity_result != 0:
        report["status"] = "FAIL"
    report_path = args.output_dir / f"{args.profile}_capacity_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 5


if __name__ == "__main__":
    raise SystemExit(main())
