#!/usr/bin/env python3
"""Run the non-shortenable 72-hour P5 soak workload in isolated staging."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.capacity_gate import load_capacity_spec
from app.services.hardware_inventory import detect_hardware, hardware_shortfalls
from app.services.soak_report import build_soak_report


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    parser.add_argument("--metrics-container", required=True)
    parser.add_argument("--compose-project", required=True)
    parser.add_argument("--duration-seconds", type=int, default=259200)
    parser.add_argument("--recovery-seconds", type=int, default=600)
    parser.add_argument("--spawn-rate", type=int, default=5)
    args = parser.parse_args()
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
    for path in (
        args.document_fixture,
        args.audio_fixture,
        args.video_fixture,
        args.credentials,
        args.grounding_evidence,
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
    with (args.output_dir / "soak_collector.log").open("w", encoding="utf-8") as log:
        collector = subprocess.Popen(
            collector_command,
            cwd=ROOT,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        with (args.output_dir / "soak_locust.log").open(
            "w", encoding="utf-8"
        ) as load_log:
            load = subprocess.run(
                locust_command,
                cwd=ROOT,
                env=environment,
                stdout=load_log,
                stderr=subprocess.STDOUT,
                check=False,
            )
        collector_exit = collector.wait(timeout=total_collection + 180)
    completed = datetime.now(UTC)
    report = build_soak_report(
        profile_name=args.profile,
        users=users,
        observed_hardware=observed_hardware,
        started_at=started.isoformat(),
        completed_at=completed.isoformat(),
        duration_seconds=args.duration_seconds,
        locust_stats_path=Path(str(prefix) + "_stats.csv"),
        telemetry_path=telemetry,
        locust_exit_code=load.returncode,
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
