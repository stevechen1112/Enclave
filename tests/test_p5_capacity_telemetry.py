from __future__ import annotations

from app.services.capacity_telemetry import (
    parse_docker_stats,
    parse_prometheus_text,
    summarize_samples,
    telemetry_snapshot,
)

PROMETHEUS = """
# HELP ignored ignored
http_requests_total{method="GET",endpoint="/health",status="200"} 99
http_requests_total{method="POST",endpoint="/chat",status="500"} 1
http_request_duration_seconds_count{method="GET",endpoint="/health"} 100
http_request_duration_seconds_sum{method="GET",endpoint="/health"} 12.5
enclave_db_pool_connections{state="size"} 10
enclave_db_pool_connections{state="checked_out"} 4
enclave_redis_memory_ratio 0.25
enclave_celery_queue_depth 7
enclave_object_io_duration_seconds_count{backend="s3",operation="put",ok="true"} 3
enclave_object_io_duration_seconds_sum{backend="s3",operation="put",ok="true"} 0.6
enclave_provider_duration_seconds_count{provider="ollama",ok="true"} 2
enclave_provider_duration_seconds_sum{provider="ollama",ok="true"} 1.5
"""


def test_prometheus_snapshot_covers_p5_runtime_metrics():
    snapshot = telemetry_snapshot(parse_prometheus_text(PROMETHEUS))
    assert snapshot["api_request_count"] == 100
    assert snapshot["api_error_count"] == 1
    assert snapshot["db_pool_percent"] == 40
    assert snapshot["redis_memory_ratio"] == 0.25
    assert snapshot["celery_queue_depth"] == 7
    assert snapshot["object_io_count"] == 3
    assert snapshot["provider_count"] == 2


def test_docker_stats_and_sample_summary_are_machine_readable():
    rows = parse_docker_stats(
        '{"Name":"enclave-web","CPUPerc":"12.5%","MemPerc":"33.0%",'
        '"MemUsage":"330MiB / 1GiB","BlockIO":"1MB / 2MB","NetIO":"3MB / 4MB"}\n'
    )
    assert rows[0]["cpu_percent"] == 12.5
    summary = summarize_samples(
        [
            {
                "health_status": 200,
                "runtime": {
                    "db_pool_percent": 40,
                    "redis_memory_ratio": 0.25,
                    "celery_queue_depth": 7,
                },
                "containers": rows,
            }
        ]
    )
    assert summary["sample_count"] == 1
    assert summary["max_redis_memory_percent"] == 25
    assert summary["max_container_memory_percent"] == 33
