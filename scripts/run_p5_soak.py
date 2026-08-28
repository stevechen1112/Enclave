#!/usr/bin/env python3
"""Run the non-shortenable 72-hour P5 soak workload in isolated staging."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.capacity_gate import load_capacity_spec
from app.services.hardware_inventory import (
    co_resident_enclave_projects,
    compose_container_identity,
    detect_hardware,
    hardware_boundary_errors,
    hardware_shortfalls,
)
from app.services.p5_evidence_binding import (
    load_environment_evidence,
    require_environment_binding,
    runtime_identity_matches_environment,
)
from app.services.soak_report import build_soak_report


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stop_process(process: subprocess.Popen | None, *, timeout: int = 60) -> int:
    if process is None:
        return -1
    if process.poll() is None:
        process.terminate()
        try:
            return int(process.wait(timeout=timeout))
        except subprocess.TimeoutExpired:
            process.kill()
            return int(process.wait(timeout=30))
    return int(process.returncode if process.returncode is not None else -1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--profile", choices=("lite", "standard", "enterprise"), default="standard"
    )
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--document-fixture", type=Path, required=True)
    parser.add_argument("--audio-fixture", type=Path, required=True)
    parser.add_argument("--video-fixture", type=Path, required=True)
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--grounding-evidence", type=Path, required=True)
    parser.add_argument("--environment-evidence", type=Path, required=True)
    parser.add_argument("--metrics-container", required=True)
    parser.add_argument("--compose-project", required=True)
    parser.add_argument("--duration-seconds", type=int, default=259200)
    parser.add_argument("--recovery-seconds", type=int, default=600)
    parser.add_argument("--spawn-rate", type=int, default=5)
    parser.add_argument("--confirm-isolated-staging", action="store_true")
    args = parser.parse_args()
    if not args.confirm_isolated_staging:
        parser.error("--confirm-isolated-staging is required")
    if args.profile != "standard":
        parser.error("formal 72-hour soak must use the Standard profile")
    if args.recovery_seconds < 0 or args.spawn_rate <= 0:
        parser.error("recovery seconds must be non-negative and spawn rate positive")
    spec = load_capacity_spec()
    required = int(spec["test_policy"]["soak_min_duration_seconds"])
    if args.duration_seconds < required:
        parser.error(f"soak duration cannot be shorter than {required} seconds")
    observed_hardware = detect_hardware(ROOT)
    shortfalls = hardware_shortfalls(
        observed_hardware, spec["profiles"][args.profile]["hardware"]
    )
    if shortfalls:
        parser.error("host does not qualify for profile: " + "; ".join(shortfalls))
    boundary_errors = hardware_boundary_errors(
        observed_hardware, spec["profiles"][args.profile]["hardware"]
    )
    if boundary_errors:
        parser.error(
            "host is outside the formal profile boundary: "
            + "; ".join(boundary_errors)
        )
    co_resident = co_resident_enclave_projects(args.compose_project)
    if co_resident:
        parser.error(
            "soak host is not isolated; co-resident Enclave projects: "
            + ", ".join(co_resident)
        )
    try:
        metrics_identity = compose_container_identity(
            args.metrics_container, args.compose_project
        )
    except ValueError as exc:
        parser.error(f"metrics container binding failed: {exc}")
    for path in (
        args.document_fixture,
        args.audio_fixture,
        args.video_fixture,
        args.credentials,
        args.grounding_evidence,
        args.environment_evidence,
    ):
        if not path.is_file():
            parser.error(f"missing fixture: {path}")
    grounding = json.loads(args.grounding_evidence.read_text(encoding="utf-8"))
    grounding["artifact_sha256"] = _sha256(args.grounding_evidence)
    if (
        grounding.get("status") != "PASS"
        or grounding.get("execution_class") != "live"
        or grounding.get("publication_class") != "isolated_staging_fixture"
        or not str(grounding.get("kb_revision_id") or "").strip()
        or int(grounding.get("search_results", 0) or 0) <= 0
        or int(grounding.get("chat_sources", 0) or 0) <= 0
        or len(str(grounding.get("source_commit") or "")) != 40
        or not str(grounding.get("tenant_id") or "").strip()
    ):
        parser.error("grounding evidence is not a complete live PASS")
    try:
        environment_evidence = load_environment_evidence(args.environment_evidence)
        require_environment_binding(
            environment_evidence,
            source_commit=str(grounding["source_commit"]),
            compose_project=args.compose_project,
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        parser.error(f"environment evidence binding failed: {exc}")
    if environment_evidence.get("observed_hardware") != observed_hardware:
        parser.error("soak host hardware does not match environment evidence")
    if not runtime_identity_matches_environment(environment_evidence, metrics_identity):
        parser.error("soak runtime image does not match environment evidence")
    environment = os.environ.copy()
    for name in (
        "LOAD_TEST_USER_PASSWORD",
        "LOAD_TEST_ADMIN_PASSWORD",
        "LOAD_TEST_SUPERUSER_PASSWORD",
    ):
        if not environment.get(name):
            parser.error(f"{name} must be injected")
    environment.update(
        {
            "CAPACITY_PROFILE": args.profile,
            "LOAD_TEST_CLASS": "soak",
            "LOAD_MULTIPLIER": "1",
            "P5_FULL_SCENARIO": "true",
            "LOAD_DOCUMENT_FIXTURE_PATH": str(args.document_fixture.resolve()),
            "LOAD_AUDIO_FIXTURE_PATH": str(args.audio_fixture.resolve()),
            "LOAD_VIDEO_FIXTURE_PATH": str(args.video_fixture.resolve()),
            "LOAD_TEST_CREDENTIALS_PATH": str(args.credentials.resolve()),
        }
    )
    # Soak uses the expected peak, not the 2x capacity target.
    users = int(spec["profiles"][args.profile]["expected_peak"]["concurrent_users"])
    args.output_dir.mkdir(parents=True, exist_ok=True)
    prefix = args.output_dir / "soak"
    telemetry = args.output_dir / "soak_telemetry.jsonl"
    telemetry_summary = args.output_dir / "soak_telemetry_summary.json"
    formal_artifacts = (
        Path(str(prefix) + "_stats.csv"),
        telemetry,
        telemetry_summary,
        args.output_dir / "soak_report.json",
        args.output_dir / "soak_collector.log",
        args.output_dir / "soak_locust.log",
    )
    if any(path.exists() for path in formal_artifacts):
        parser.error("formal soak requires a fresh output directory")

    import httpx

    credentials = json.loads(args.credentials.read_text(encoding="utf-8"))
    if not isinstance(credentials, list) or len(credentials) < users:
        parser.error("credential pool is smaller than expected peak users")
    tokens = [
        str(row.get("access_token") or "")
        for row in credentials[:users]
        if isinstance(row, dict)
    ]
    if len(tokens) != users or any(not token for token in tokens):
        parser.error("credential pool does not contain enough access tokens")
    if len(set(tokens)) != users:
        parser.error("formal soak requires one unique access token per user")
    try:
        with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=30) as client:
            health = client.get("/health")
            health.raise_for_status()
            health_payload = health.json()
            release = health_payload.get("release", {})
            if (
                health_payload.get("env") != "staging"
                or release.get("identifiable") is not True
                or release.get("source_commit") != grounding.get("source_commit")
            ):
                parser.error("runtime release does not match grounding evidence")
            expected_tenant = str(grounding.get("tenant_id") or "")
            for token in tokens:
                me = client.get(
                    "/api/v1/users/me",
                    headers={"Authorization": f"Bearer {token}"},
                )
                me.raise_for_status()
                if str(me.json().get("tenant_id") or "") != expected_tenant:
                    parser.error("credential tenant does not match grounding evidence")
    except (httpx.HTTPError, TypeError, ValueError, json.JSONDecodeError) as exc:
        parser.error(f"soak live preflight failed: {exc}")
    total_collection = args.duration_seconds + max(0, args.recovery_seconds)
    collector_command = [
        sys.executable,
        str(ROOT / "scripts" / "collect_p5_telemetry.py"),
        "--base-url",
        args.base_url,
        "--output",
        str(telemetry),
        "--summary",
        str(telemetry_summary),
        "--duration-seconds",
        str(total_collection),
        "--interval-seconds",
        str(spec["test_policy"]["telemetry_sample_interval_seconds"]),
        "--docker-stats",
        "--metrics-container",
        args.metrics_container,
        "--compose-project",
        args.compose_project,
    ]
    if int(spec["profiles"][args.profile]["hardware"].get("gpu_vram_gb", 0)) > 0:
        collector_command.append("--gpu-stats")
    locust_command = [
        sys.executable,
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
    started_monotonic = time.monotonic()
    collector: subprocess.Popen | None = None
    load: subprocess.Popen | None = None
    collector_exit = -1
    load_exit = -1
    load_completed = started
    actual_load_seconds = 0
    interval = int(spec["test_policy"]["telemetry_sample_interval_seconds"])
    with (
        (args.output_dir / "soak_collector.log").open(
            "w", encoding="utf-8"
        ) as log,
        (args.output_dir / "soak_locust.log").open(
            "w", encoding="utf-8"
        ) as load_log,
    ):
        try:
            collector = subprocess.Popen(
                collector_command,
                cwd=ROOT,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            load = subprocess.Popen(
                locust_command,
                cwd=ROOT,
                env=environment,
                stdout=load_log,
                stderr=subprocess.STDOUT,
            )
            while load.poll() is None:
                if collector.poll() is not None:
                    _stop_process(load)
                    break
                time.sleep(5)
            load_exit = int(load.poll() if load.poll() is not None else -1)
            load_completed = datetime.now(UTC)
            actual_load_seconds = int(time.monotonic() - started_monotonic)
            load_finished_early = actual_load_seconds + 5 < args.duration_seconds
            if load_exit != 0 or load_finished_early or collector.poll() is not None:
                if collector.poll() is None:
                    collector_exit = _stop_process(collector)
                else:
                    collector_exit = int(collector.returncode or 0)
            else:
                try:
                    collector_exit = int(
                        collector.wait(
                            timeout=args.recovery_seconds + interval + 180
                        )
                    )
                except subprocess.TimeoutExpired:
                    collector_exit = _stop_process(collector)
        finally:
            for process in (load, collector):
                if process is not None and process.poll() is None:
                    _stop_process(process, timeout=30)
    report = build_soak_report(
        profile_name=args.profile,
        users=users,
        observed_hardware=observed_hardware,
        started_at=started.isoformat(),
        completed_at=load_completed.isoformat(),
        duration_seconds=actual_load_seconds,
        target_duration_seconds=args.duration_seconds,
        source_commit=str(grounding["source_commit"]),
        compose_project=args.compose_project,
        metrics_container_identity=metrics_identity,
        environment_artifact_sha256=str(
            environment_evidence["artifact_sha256"]
        ),
        expected_runtime_images=dict(environment_evidence["runtime_images"]),
        locust_stats_path=Path(str(prefix) + "_stats.csv"),
        telemetry_path=telemetry,
        locust_exit_code=load_exit,
        collector_exit_code=collector_exit,
        grounding=grounding,
    )
    (args.output_dir / "soak_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 6


if __name__ == "__main__":
    raise SystemExit(main())
