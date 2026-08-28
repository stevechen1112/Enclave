"""Pure helpers for P5 Prometheus and container telemetry samples."""

from __future__ import annotations

import json
import re
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
    cpu_values = [
        float(container["cpu_percent"])
        for sample in samples
        for container in sample.get("containers", [])
        if container.get("cpu_percent") is not None
    ]
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
        "max_container_cpu_percent": max(cpu_values, default=None),
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
