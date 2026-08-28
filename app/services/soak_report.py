"""Build a 72-hour P5 soak report from immutable raw artifacts."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

from app.services.capacity_gate import load_capacity_spec
from app.services.capacity_report import read_jsonl, read_locust_stats
from app.services.capacity_telemetry import summarize_samples
from app.services.hardware_inventory import hardware_shortfalls


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _delta(samples: list[dict[str, Any]], field: str) -> float:
    values = [
        float(sample["runtime"][field])
        for sample in samples
        if sample.get("runtime", {}).get(field) is not None
    ]
    return max(0.0, values[-1] - values[0]) if len(values) >= 2 else 0.0


def build_soak_report(
    *,
    profile_name: str,
    users: int,
    observed_hardware: dict[str, Any],
    started_at: str,
    completed_at: str,
    duration_seconds: int,
    locust_stats_path: Path,
    telemetry_path: Path,
    locust_exit_code: int,
    collector_exit_code: int,
) -> dict[str, Any]:
    spec = load_capacity_spec()
    policy = spec["test_policy"]
    samples = read_jsonl(telemetry_path)
    summary = summarize_samples(samples)
    stats = read_locust_stats(locust_stats_path)
    aggregate = stats.get("Aggregated", {})
    requests = int(float(aggregate.get("Request Count", 0) or 0))
    failures = int(float(aggregate.get("Failure Count", 0) or 0))
    error_rate = failures / requests if requests else 1.0
    rpm = requests / max(1, duration_seconds) * 60
    profile = spec["profiles"][profile_name]
    hardware_errors = hardware_shortfalls(observed_hardware, profile["hardware"])
    scenario_rows = []
    for name in spec["required_scenarios"]:
        row = stats.get(name, {})
        count = int(float(row.get("Request Count", 0) or 0))
        failed = int(float(row.get("Failure Count", 0) or 0))
        scenario_error_rate = failed / count if count else 1.0
        scenario_rows.append(
            {
                "scenario": name,
                "status": (
                    "PASS"
                    if count > 0
                    and scenario_error_rate <= float(profile["slo"]["api_error_rate"])
                    else "FAIL"
                ),
                "requests": count,
                "failures": failed,
                "error_rate": round(scenario_error_rate, 6),
            }
        )
    exhaustion = int(_delta(samples, "db_pool_exhaustion_count"))
    ending_backlog = summary.get("ending_queue_depth")
    starting_backlog = summary.get("starting_queue_depth")
    unrecoverable = (
        int(max(0, ending_backlog - starting_backlog))
        if ending_backlog is not None and starting_backlog is not None
        else -1
    )
    required_samples = math.ceil(
        (
            policy["soak_min_duration_seconds"]
            / policy["telemetry_sample_interval_seconds"]
        )
        * policy["soak_min_sample_ratio"]
    )
    memory_growth = summary.get("memory_growth_percent")
    passed = (
        locust_exit_code == 0
        and collector_exit_code == 0
        and duration_seconds >= int(policy["soak_min_duration_seconds"])
        and not hardware_errors
        and len(samples) >= required_samples
        and memory_growth is not None
        and memory_growth <= float(policy["max_memory_growth_percent"])
        and exhaustion <= int(policy["max_db_pool_exhaustion_events"])
        and unrecoverable <= int(policy["max_unrecoverable_backlog"])
        and error_rate <= float(spec["profiles"][profile_name]["slo"]["api_error_rate"])
        and users >= int(profile["expected_peak"]["concurrent_users"])
        and rpm >= float(profile["expected_peak"]["requests_per_minute"])
        and all(row["status"] == "PASS" for row in scenario_rows)
    )
    return {
        "profile": profile_name,
        "status": "PASS" if passed else "FAIL",
        "execution_class": "live",
        "started_at": started_at,
        "completed_at": completed_at,
        "duration_seconds": duration_seconds,
        "observed_hardware": observed_hardware,
        "hardware_shortfalls": hardware_errors,
        "achieved_load": {
            "concurrent_users": users,
            "requests_per_minute": round(rpm, 3),
        },
        "scenarios": scenario_rows,
        "telemetry_sample_count": len(samples),
        "memory_growth_percent": memory_growth,
        "db_pool_exhaustion_events": exhaustion,
        "ending_unrecoverable_backlog": unrecoverable,
        "request_count": requests,
        "error_rate": round(error_rate, 6),
        "telemetry_summary": summary,
        "runner": {
            "locust_exit_code": locust_exit_code,
            "collector_exit_code": collector_exit_code,
        },
        "raw_artifacts": {
            "locust_stats_sha256": _sha256(locust_stats_path),
            "telemetry_sha256": _sha256(telemetry_path),
        },
    }
