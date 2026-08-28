"""Pure helpers for P5 Prometheus and container telemetry samples."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from itertools import pairwise
from typing import Any

_LINE = re.compile(
    r"^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)(?P<labels>\{[^}]*\})?\s+"
    r"(?P<value>-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|[+-]?Inf|NaN)$"
)


def parse_prometheus_text(text: str) -> dict[str, float]:
    values: dict[str, float] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _LINE.match(line)
        if match is None:
            continue
        key = match.group("name") + (match.group("labels") or "")
        try:
            values[key] = float(match.group("value"))
        except ValueError:
            continue
    return values


def metric_value(
    metrics: dict[str, float], name: str, *, labels: dict[str, str] | None = None
) -> float | None:
    for key, value in metrics.items():
        if key == name and not labels:
            return value
        if not key.startswith(name + "{"):
            continue
        if labels and all(
            f'{label}="{expected}"' in key for label, expected in labels.items()
        ):
            return value
    return None


def metric_sum(metrics: dict[str, float], prefix: str) -> float:
    return sum(value for key, value in metrics.items() if key.startswith(prefix))


def telemetry_snapshot(metrics: dict[str, float]) -> dict[str, Any]:
    pool_size = metric_value(
        metrics, "enclave_db_pool_connections", labels={"state": "size"}
    )
    checked_out = metric_value(
        metrics, "enclave_db_pool_connections", labels={"state": "checked_out"}
    )
    provider_count = metric_sum(metrics, "enclave_provider_duration_seconds_count")
    provider_error_count = sum(
        value
        for key, value in metrics.items()
        if key.startswith("enclave_provider_duration_seconds_count")
        and 'ok="false"' in key
    )
    provider_sum = metric_sum(metrics, "enclave_provider_duration_seconds_sum")
    object_count = metric_sum(metrics, "enclave_object_io_duration_seconds_count")
    object_error_count = sum(
        value
        for key, value in metrics.items()
        if key.startswith("enclave_object_io_duration_seconds_count")
        and 'ok="false"' in key
    )
    object_sum = metric_sum(metrics, "enclave_object_io_duration_seconds_sum")
    request_count = metric_sum(metrics, "http_requests_total")
    request_duration_count = metric_sum(metrics, "http_request_duration_seconds_count")
    request_duration_sum = metric_sum(metrics, "http_request_duration_seconds_sum")
    failed = sum(
        value
        for key, value in metrics.items()
        if key.startswith("http_requests_total")
        and any(f'status="{code}"' in key for code in range(500, 600))
    )
    return {
        "api_request_count": request_count,
        "api_error_count": failed,
        "api_duration_count": request_duration_count,
        "api_duration_sum_seconds": request_duration_sum,
        "db_pool_size": pool_size,
        "db_pool_checked_out": checked_out,
        "db_pool_percent": (
            checked_out / pool_size * 100
            if pool_size is not None and checked_out is not None and pool_size > 0
            else None
        ),
        "redis_memory_ratio": metric_value(metrics, "enclave_redis_memory_ratio"),
        "celery_queue_depth": metric_value(metrics, "enclave_celery_queue_depth"),
        "db_pool_exhaustion_count": metric_value(
            metrics, "enclave_db_pool_exhaustion_total"
        )
        or 0.0,
        "object_io_count": object_count,
        "object_io_error_count": object_error_count,
        "object_io_sum_seconds": object_sum,
        "provider_count": provider_count,
        "provider_error_count": provider_error_count,
        "provider_sum_seconds": provider_sum,
    }


def parse_docker_stats(lines: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in lines.splitlines():
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue

        def _percent(value: Any) -> float | None:
            try:
                return float(str(value).strip().rstrip("%"))
            except ValueError:
                return None

        rows.append(
            {
                "name": raw.get("Name") or raw.get("Container"),
                "cpu_percent": _percent(raw.get("CPUPerc")),
                "memory_percent": _percent(raw.get("MemPerc")),
                "memory_usage": raw.get("MemUsage"),
                "block_io": raw.get("BlockIO"),
                "network_io": raw.get("NetIO"),
            }
        )
    return rows


def summarize_samples(samples: list[dict[str, Any]]) -> dict[str, Any]:
    def _values(field: str) -> list[float]:
        return [
            float(sample["runtime"][field])
            for sample in samples
            if sample.get("runtime", {}).get(field) is not None
        ]

    memory_values = [
        float(container["memory_percent"])
        for sample in samples
        for container in sample.get("containers", [])
        if container.get("memory_percent") is not None
    ]
    host_cpu_values = []
    for sample in samples:
        cores = int(sample.get("host_cpu_cores", 0) or 0)
        cpu_total = sum(
            float(container["cpu_percent"])
            for container in sample.get("containers", [])
            if container.get("cpu_percent") is not None
        )
        if cores > 0:
            host_cpu_values.append(cpu_total / cores)
    gpu_values = [
        float(gpu["utilization_percent"])
        for sample in samples
        for gpu in sample.get("gpus", [])
        if gpu.get("utilization_percent") is not None
    ]
    first_memory = next(
        (
            max(
                float(container["memory_percent"])
                for container in sample.get("containers", [])
                if container.get("memory_percent") is not None
            )
            for sample in samples
            if any(
                container.get("memory_percent") is not None
                for container in sample.get("containers", [])
            )
        ),
        None,
    )
    last_memory = next(
        (
            max(
                float(container["memory_percent"])
                for container in sample.get("containers", [])
                if container.get("memory_percent") is not None
            )
            for sample in reversed(samples)
            if any(
                container.get("memory_percent") is not None
                for container in sample.get("containers", [])
            )
        ),
        None,
    )
    queue_values = _values("celery_queue_depth")
    return {
        "sample_count": len(samples),
        "max_db_pool_percent": max(_values("db_pool_percent"), default=None),
        "max_redis_memory_percent": (
            max(_values("redis_memory_ratio"), default=0) * 100
            if _values("redis_memory_ratio")
            else None
        ),
        "max_celery_queue_depth": max(_values("celery_queue_depth"), default=None),
        "max_container_memory_percent": max(memory_values, default=None),
        "max_host_cpu_percent": max(host_cpu_values, default=None),
        "max_gpu_percent": max(gpu_values, default=None),
        "memory_growth_percent": (
            round(last_memory - first_memory, 6)
            if first_memory is not None and last_memory is not None
            else None
        ),
        "starting_queue_depth": queue_values[0] if queue_values else None,
        "ending_queue_depth": queue_values[-1] if queue_values else None,
        "health_failures": sum(
            1 for sample in samples if sample.get("health_status") != 200
        ),
        "metrics_failures": sum(1 for sample in samples if sample.get("metrics_error")),
    }


def _timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def validate_telemetry_integrity(
    samples: list[dict[str, Any]],
    *,
    started_at: str,
    completed_at: str,
    source_commit: str,
    interval_seconds: int,
    gpu_required: bool,
    invalid_json_lines: int,
) -> dict[str, Any]:
    """Bind telemetry coverage and every sample to one staging release."""
    errors: list[str] = []
    started = _timestamp(started_at)
    completed = _timestamp(completed_at)
    captured = [_timestamp(sample.get("captured_at")) for sample in samples]
    if started is None or completed is None or completed < started:
        errors.append("runner timestamps are invalid")
    if interval_seconds <= 0:
        errors.append("telemetry interval must be positive")
    if invalid_json_lines:
        errors.append("telemetry contains invalid JSON lines")
    if not samples or any(value is None for value in captured):
        errors.append("telemetry timestamps are incomplete")
    valid_captured = [value for value in captured if value is not None]
    gaps: list[float] = []
    if len(valid_captured) >= 2:
        gaps = [
            (current - previous).total_seconds()
            for previous, current in pairwise(valid_captured)
        ]
        if any(gap <= 0 for gap in gaps):
            errors.append("telemetry timestamps are not strictly increasing")
        if interval_seconds > 0 and any(
            gap > interval_seconds * 2.5 for gap in gaps
        ):
            errors.append("telemetry contains an excessive sampling gap")
    if (
        started
        and valid_captured
        and interval_seconds > 0
        and abs((valid_captured[0] - started).total_seconds()) > interval_seconds
    ):
        errors.append("telemetry did not begin with the load run")
    if (
        completed
        and valid_captured
        and interval_seconds > 0
        and valid_captured[-1] < completed - timedelta(seconds=interval_seconds)
    ):
        errors.append("telemetry does not cover the completed load run")
    for index, sample in enumerate(samples):
        health = sample.get("health") if isinstance(sample.get("health"), dict) else {}
        release = health.get("release") if isinstance(health.get("release"), dict) else {}
        if sample.get("health_status") != 200:
            errors.append(f"telemetry health failure at sample {index}")
        if health.get("env") != "staging" or release.get("identifiable") is not True:
            errors.append(f"telemetry release identity failure at sample {index}")
        if release.get("source_commit") != source_commit:
            errors.append(f"telemetry source commit mismatch at sample {index}")
        if sample.get("metrics_error") or not sample.get("runtime"):
            errors.append(f"telemetry metrics failure at sample {index}")
        if sample.get("container_error") or not sample.get("containers"):
            errors.append(f"telemetry container failure at sample {index}")
        if gpu_required and (sample.get("gpu_error") or not sample.get("gpus")):
            errors.append(f"telemetry GPU failure at sample {index}")
    return {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "invalid_json_lines": invalid_json_lines,
        "first_sample_at": valid_captured[0].isoformat() if valid_captured else None,
        "last_sample_at": valid_captured[-1].isoformat() if valid_captured else None,
        "max_gap_seconds": max(gaps, default=None),
    }
