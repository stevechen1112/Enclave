from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.services.soak_report import build_soak_report


def test_short_soak_artifacts_cannot_pass(tmp_path: Path):
    stats = tmp_path / "stats.csv"
    stats.write_text(
        "Type,Name,Request Count,Failure Count,95%\nGET,Aggregated,1000,0,100\n",
        encoding="utf-8",
    )
    telemetry = tmp_path / "telemetry.jsonl"
    samples = []
    for index in range(2):
        samples.append(
            {
                "captured_at": (
                    datetime.now(UTC) + timedelta(minutes=index)
                ).isoformat(),
                "health_status": 200,
                "runtime": {
                    "db_pool_percent": 10,
                    "redis_memory_ratio": 0.1,
                    "celery_queue_depth": 0,
                    "db_pool_exhaustion_count": 0,
                },
                "containers": [{"cpu_percent": 10, "memory_percent": 10}],
            }
        )
    telemetry.write_text(
        "".join(json.dumps(sample) + "\n" for sample in samples), encoding="utf-8"
    )
    report = build_soak_report(
        profile_name="standard",
        users=100,
        observed_hardware={
            "cpu_cores": 8,
            "ram_gb": 32,
            "disk_gb": 200,
            "gpu_vram_gb": 8,
        },
        started_at=samples[0]["captured_at"],
        completed_at=samples[-1]["captured_at"],
        duration_seconds=60,
        locust_stats_path=stats,
        telemetry_path=telemetry,
        locust_exit_code=0,
        collector_exit_code=0,
        grounding={
            "status": "PASS",
            "execution_class": "live",
            "source_commit": "a" * 40,
            "tenant_id": "11111111-1111-1111-1111-111111111111",
            "search_results": 1,
            "chat_sources": 1,
            "artifact_sha256": "a" * 64,
        },
    )
    assert report["status"] == "FAIL"
    assert report["telemetry_sample_count"] == 2
    assert len(report["raw_artifacts"]["telemetry_sha256"]) == 64
