from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.services.capacity_gate import load_capacity_spec, profile_load_target
from app.services.capacity_report import build_capacity_report


def test_report_fails_closed_when_required_workload_or_provider_metric_is_missing(
    tmp_path: Path,
):
    spec = load_capacity_spec()
    names = ["Aggregated", *spec["required_scenarios"]]
    rows = [
        "Type,Name,Request Count,Failure Count,95%",
        *[
            f"GET,{name},{40000 if name == 'Aggregated' else 100},0,100"
            for name in names
            if name != "video_queue"
        ],
    ]
    stats = tmp_path / "stats.csv"
    stats.write_text("\n".join(rows), encoding="utf-8")
    telemetry = tmp_path / "telemetry.jsonl"
    sample = {
        "captured_at": datetime.now(UTC).isoformat(),
        "health_status": 200,
        "health": {
            "env": "staging",
            "release": {"identifiable": True, "source_commit": "a" * 40},
        },
        "runtime": {
            "db_pool_percent": 10,
            "redis_memory_ratio": 0.1,
            "celery_queue_depth": 0,
            "object_io_count": 0,
            "provider_count": 0,
            "provider_error_count": 0,
        },
        "containers": [{"cpu_percent": 10, "memory_percent": 10}],
        "gpus": [],
    }
    telemetry.write_text(json.dumps(sample) + "\n", encoding="utf-8")
    completed = datetime.now(UTC)
    started = (completed - timedelta(seconds=900)).isoformat()
    completed_text = completed.isoformat()
    report = build_capacity_report(
        profile_name="lite",
        users=int(profile_load_target(spec, "lite")["concurrent_users"]),
        duration_seconds=900,
        started_at=started,
        completed_at=completed_text,
        locust_stats_path=stats,
        telemetry_path=telemetry,
        integrity={
            "status": "PASS",
            "data_corruption": 0,
            "cross_tenant_leak": 0,
            "unrecoverable_backlog": 0,
            "execution_class": "live",
            "artifact_sha256": "a" * 64,
            "tenant_isolation_status": "PASS",
            "job_reconciliation_status": "PASS",
            "source_commit": "a" * 40,
            "tenant_id": "11111111-1111-1111-1111-111111111111",
            "run_started_at": started,
            "load_completed_at": completed_text,
        },
        grounding={
            "status": "PASS",
            "execution_class": "live",
            "publication_class": "isolated_staging_fixture",
            "kb_revision_id": "22222222-2222-2222-2222-222222222222",
            "marker": "P5-SOP-RESET-042",
            "source_commit": "a" * 40,
            "tenant_id": "11111111-1111-1111-1111-111111111111",
            "search_results": 1,
            "chat_sources": 1,
            "artifact_sha256": "b" * 64,
        },
        observed_hardware={
            "cpu_cores": 4,
            "ram_gb": 8,
            "disk_gb": 50,
            "gpu_vram_gb": 0,
        },
        source_commit="a" * 40,
        compose_project="enclave-p5",
        metrics_container_identity={
            "container": "enclave-p5-web-1",
            "compose_project": "enclave-p5",
            "compose_service": "web",
            "running": True,
            "image_id": "sha256:" + "b" * 64,
        },
        backend_container_identity={
            "container": "enclave-p5-worker-1",
            "compose_project": "enclave-p5",
            "compose_service": "worker",
            "running": True,
            "image_id": "sha256:" + "b" * 64,
        },
        telemetry_interval_seconds=60,
    )
    assert report["status"] == "FAIL"
    assert (
        next(row for row in report["scenarios"] if row["scenario"] == "video_queue")[
            "status"
        ]
        == "FAIL"
    )
    assert (
        next(row for row in report["telemetry"] if row["metric"] == "provider_latency")[
            "status"
        ]
        == "FAIL"
    )
