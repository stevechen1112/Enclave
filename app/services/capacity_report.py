"""Build a P5 profile report from Locust CSV and telemetry artifacts."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from app.services.capacity_gate import capacity_spec_sha256, load_capacity_spec
from app.services.capacity_telemetry import summarize_samples
from app.services.hardware_inventory import hardware_shortfalls


def read_locust_stats(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            name = str(row.get("Name") or "").strip()
            if name:
                rows[name] = row
    return rows


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _number(row: dict[str, Any], *names: str) -> float:
    for name in names:
        try:
            return float(row.get(name, 0) or 0)
        except ValueError:
            continue
    return 0.0


def _delta(samples: list[dict[str, Any]], field: str) -> float:
    values = [
        float(sample["runtime"][field])
        for sample in samples
        if sample.get("runtime", {}).get(field) is not None
    ]
    return max(0.0, values[-1] - values[0]) if len(values) >= 2 else 0.0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_capacity_report(
    *,
    profile_name: str,
    users: int,
    duration_seconds: int,
    started_at: str,
    completed_at: str,
    locust_stats_path: Path,
    telemetry_path: Path,
    integrity: dict[str, int],
    grounding: dict[str, Any],
    observed_hardware: dict[str, Any],
    execution_class: str = "live",
) -> dict[str, Any]:
    spec = load_capacity_spec()
    profile = spec["profiles"][profile_name]
    hardware_errors = hardware_shortfalls(observed_hardware, profile["hardware"])
    stats = read_locust_stats(locust_stats_path)
    samples = read_jsonl(telemetry_path)
    telemetry_summary = summarize_samples(samples)
    total = stats.get("Aggregated", {})
    requests = int(_number(total, "Request Count"))
    failures = int(_number(total, "Failure Count"))
    rpm = requests / max(1, duration_seconds) * 60
    error_rate = failures / requests if requests else 1.0
    slo = profile["slo"]
    scenario_limits = {
        "auth_login": 5000,
        "asset_list": slo["search_p95_ms"],
        "knowledge_search": slo["search_p95_ms"],
        "grounded_chat": slo["chat_p95_ms"],
        "document_upload": slo["upload_p95_ms"],
        "batch_ingestion": slo["upload_p95_ms"],
        "audio_queue": slo["upload_p95_ms"],
        "video_queue": slo["upload_p95_ms"],
    }
    scenarios = []
    for name in spec["required_scenarios"]:
        row = stats.get(name, {})
        count = int(_number(row, "Request Count"))
        failed = int(_number(row, "Failure Count"))
        p95 = _number(row, "95%", "95%ile")
        scenario_error_rate = failed / count if count else 1.0
        passed = (
            count > 0
            and scenario_error_rate <= float(slo["api_error_rate"])
            and p95 <= float(scenario_limits[name])
        )
        scenarios.append(
            {
                "scenario": name,
                "status": "PASS" if passed else "FAIL",
                "requests": count,
                "failures": failed,
                "error_rate": round(scenario_error_rate, 6),
                "p95_ms": p95,
                "p95_limit_ms": scenario_limits[name],
            }
        )

    limits = profile["resource_limits"]
    object_count = _delta(samples, "object_io_count")
    provider_count = _delta(samples, "provider_count")
    provider_errors = _delta(samples, "provider_error_count")
    provider_error_rate = provider_errors / provider_count if provider_count else 0.0
    gpu_required = int(profile["hardware"].get("gpu_vram_gb", 0)) > 0
    telemetry_checks = {
        "api_latency": all(row["status"] == "PASS" for row in scenarios),
        "api_error_rate": error_rate <= float(slo["api_error_rate"]),
        "db_pool": (
            telemetry_summary["max_db_pool_percent"] is not None
            and telemetry_summary["max_db_pool_percent"] <= limits["db_pool_percent"]
        ),
        "redis_memory": (
            telemetry_summary["max_redis_memory_percent"] is not None
            and telemetry_summary["max_redis_memory_percent"]
            <= limits["redis_memory_percent"]
        ),
        "celery_backlog": (
            telemetry_summary["max_celery_queue_depth"] is not None
            and telemetry_summary["max_celery_queue_depth"] <= limits["queue_depth"]
        ),
        "object_io": object_count > 0,
        "memory": (
            telemetry_summary["max_container_memory_percent"] is not None
            and telemetry_summary["max_container_memory_percent"]
            <= limits["memory_percent"]
        ),
        "cpu": (
            telemetry_summary["max_container_cpu_percent"] is not None
            and telemetry_summary["max_container_cpu_percent"] <= limits["cpu_percent"]
        ),
        "gpu": (not gpu_required or telemetry_summary["max_gpu_percent"] is not None),
        "provider_latency": provider_count > 0,
        "provider_error_rate": (
            provider_count > 0 and provider_error_rate <= limits["provider_error_rate"]
        ),
    }
    telemetry = [
        {
            "metric": name,
            "status": "PASS" if telemetry_checks.get(name, False) else "FAIL",
        }
        for name in spec["required_telemetry"]
    ]
    target = profile["expected_peak"]
    multiplier = float(spec["test_policy"]["peak_multiplier"])
    load_passed = users >= int(
        target["concurrent_users"] * multiplier
    ) and rpm >= float(target["requests_per_minute"] * multiplier)
    grounding_passed = (
        grounding.get("status") == "PASS"
        and grounding.get("execution_class") == "live"
        and bool(str(grounding.get("marker") or "").strip())
        and len(str(grounding.get("source_commit") or "")) == 40
        and bool(str(grounding.get("tenant_id") or "").strip())
        and int(grounding.get("search_results", 0) or 0) > 0
        and int(grounding.get("chat_sources", 0) or 0) > 0
        and len(str(grounding.get("artifact_sha256") or "")) == 64
    )
    passed = (
        duration_seconds >= int(spec["test_policy"]["capacity_min_duration_seconds"])
        and not hardware_errors
        and load_passed
        and all(row["status"] == "PASS" for row in scenarios)
        and all(row["status"] == "PASS" for row in telemetry)
        and all(
            int(integrity.get(field, -1)) == 0
            for field in (
                "data_corruption",
                "cross_tenant_leak",
                "unrecoverable_backlog",
            )
        )
        and integrity.get("execution_class") == "live"
        and len(str(integrity.get("artifact_sha256") or "")) == 64
        and integrity.get("tenant_isolation_status") == "PASS"
        and integrity.get("job_reconciliation_status") == "PASS"
        and grounding_passed
    )
    return {
        "profile": profile_name,
        "status": "PASS" if passed else "FAIL",
        "execution_class": execution_class,
        "capacity_spec_sha256": capacity_spec_sha256(spec),
        "started_at": started_at,
        "completed_at": completed_at,
        "duration_seconds": duration_seconds,
        "observed_hardware": observed_hardware,
        "hardware_shortfalls": hardware_errors,
        "achieved_load": {
            "concurrent_users": users,
            "requests_per_minute": round(rpm, 3),
        },
        "request_count": requests,
        "error_rate": round(error_rate, 6),
        "scenarios": scenarios,
        "telemetry": telemetry,
        "telemetry_sample_count": len(samples),
        "telemetry_summary": telemetry_summary,
        "integrity": integrity,
        "grounding_evidence": grounding,
        "raw_artifacts": {
            "locust_stats_sha256": _sha256(locust_stats_path),
            "telemetry_sha256": _sha256(telemetry_path),
        },
    }
