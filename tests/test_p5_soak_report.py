from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.services.soak_report import build_soak_report

SOURCE_COMMIT = "a" * 40
HARDWARE = {
    "cpu_cores": 8,
    "ram_gb": 32,
    "disk_gb": 200,
    "gpu_vram_gb": 8,
}
IDENTITY = {
    "container": "enclave-p5-web-1",
    "container_id": "web-container-id",
    "compose_project": "enclave-p5",
    "compose_service": "web",
    "running": True,
    "image_id": "sha256:" + "b" * 64,
}
EXPECTED_RUNTIME = {
    "web": {
        "container": "enclave-p5-web-1",
        "container_id": "web-container-id",
        "image_id": "sha256:" + "b" * 64,
    },
    "worker": {
        "container": "enclave-p5-worker-1",
        "container_id": "worker-container-id",
        "image_id": "sha256:" + "b" * 64,
    },
}


def _grounding() -> dict:
    return {
        "status": "PASS",
        "execution_class": "live",
        "publication_class": "isolated_staging_fixture",
        "kb_revision_id": "22222222-2222-2222-2222-222222222222",
        "source_commit": SOURCE_COMMIT,
        "tenant_id": "11111111-1111-1111-1111-111111111111",
        "search_results": 1,
        "chat_sources": 1,
        "artifact_sha256": "a" * 64,
    }


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
        observed_hardware=HARDWARE,
        started_at=samples[0]["captured_at"],
        completed_at=samples[-1]["captured_at"],
        duration_seconds=60,
        target_duration_seconds=72 * 60 * 60,
        source_commit=SOURCE_COMMIT,
        compose_project="enclave-p5",
        metrics_container_identity=IDENTITY,
        environment_artifact_sha256="e" * 64,
        expected_runtime_images=EXPECTED_RUNTIME,
        locust_stats_path=stats,
        telemetry_path=telemetry,
        locust_exit_code=0,
        collector_exit_code=0,
        grounding=_grounding(),
    )
    assert report["status"] == "FAIL"
    assert report["telemetry_sample_count"] == 2
    assert len(report["raw_artifacts"]["telemetry_sha256"]) == 64


def _valid_soak(tmp_path: Path) -> tuple[dict, Path]:
    started = datetime.now(UTC) - timedelta(hours=73)
    duration = 72 * 60 * 60
    completed = started + timedelta(seconds=duration)
    stats = tmp_path / "stats.csv"
    names = (
        "auth_login",
        "asset_list",
        "knowledge_search",
        "grounded_chat",
        "document_upload",
        "batch_ingestion",
        "audio_queue",
        "video_queue",
    )
    rows = ["Type,Name,Request Count,Failure Count,95%"]
    rows.extend(f"GET,{name},648000,0,100" for name in names)
    rows.append("GET,Aggregated,5184000,0,100")
    stats.write_text("\n".join(rows) + "\n", encoding="utf-8")
    telemetry = tmp_path / "telemetry.jsonl"
    samples = []
    for index in range(864):
        samples.append(
            {
                "captured_at": (started + timedelta(seconds=index * 300)).isoformat(),
                "health_status": 200,
                "health": {
                    "env": "staging",
                    "release": {
                        "identifiable": True,
                        "source_commit": SOURCE_COMMIT,
                    },
                },
                "host_cpu_cores": 8,
                "runtime": {
                    "db_pool_percent": 10,
                    "redis_memory_ratio": 0.1,
                    "celery_queue_depth": 0,
                    "db_pool_exhaustion_count": 0,
                },
                "containers": [
                    {
                        "name": "enclave-p5-web-1",
                        "container_id": "web-container-id",
                        "image_id": "sha256:" + "b" * 64,
                        "cpu_percent": 20,
                        "memory_percent": 20,
                    },
                    {
                        "name": "enclave-p5-worker-1",
                        "container_id": "worker-container-id",
                        "image_id": "sha256:" + "b" * 64,
                        "cpu_percent": 20,
                        "memory_percent": 20,
                    },
                ],
                "gpus": [{"utilization_percent": 20}],
            }
        )
    telemetry.write_text(
        "".join(json.dumps(sample) + "\n" for sample in samples), encoding="utf-8"
    )
    kwargs = {
        "profile_name": "standard",
        "users": 100,
        "observed_hardware": HARDWARE,
        "started_at": started.isoformat(),
        "completed_at": completed.isoformat(),
        "duration_seconds": duration,
        "target_duration_seconds": duration,
        "source_commit": SOURCE_COMMIT,
        "compose_project": "enclave-p5",
        "metrics_container_identity": IDENTITY,
        "environment_artifact_sha256": "e" * 64,
        "expected_runtime_images": EXPECTED_RUNTIME,
        "locust_stats_path": stats,
        "telemetry_path": telemetry,
        "locust_exit_code": 0,
        "collector_exit_code": 0,
        "grounding": _grounding(),
    }
    return kwargs, telemetry


def test_complete_soak_requires_continuous_release_bound_telemetry(tmp_path: Path):
    kwargs, _telemetry = _valid_soak(tmp_path)
    report = build_soak_report(**kwargs)
    assert report["status"] == "PASS"
    assert report["telemetry_integrity"]["status"] == "PASS"
    assert report["telemetry_integrity"]["max_gap_seconds"] == 300


def test_soak_rejects_release_mismatch_in_one_sample(tmp_path: Path):
    kwargs, telemetry = _valid_soak(tmp_path)
    rows = telemetry.read_text(encoding="utf-8").splitlines()
    sample = json.loads(rows[100])
    sample["health"]["release"]["source_commit"] = "f" * 40
    rows[100] = json.dumps(sample)
    telemetry.write_text("\n".join(rows) + "\n", encoding="utf-8")
    report = build_soak_report(**kwargs)
    assert report["status"] == "FAIL"
    assert any(
        "source commit mismatch" in error
        for error in report["telemetry_integrity"]["errors"]
    )


def test_soak_rejects_runtime_container_replacement(tmp_path: Path):
    kwargs, telemetry = _valid_soak(tmp_path)
    rows = telemetry.read_text(encoding="utf-8").splitlines()
    sample = json.loads(rows[100])
    sample["containers"][0]["container_id"] = "replacement-container-id"
    rows[100] = json.dumps(sample)
    telemetry.write_text("\n".join(rows) + "\n", encoding="utf-8")
    report = build_soak_report(**kwargs)
    assert report["status"] == "FAIL"
    assert any(
        "runtime image mismatch" in error
        for error in report["telemetry_integrity"]["errors"]
    )


def test_soak_rejects_invalid_or_gapped_telemetry(tmp_path: Path):
    kwargs, telemetry = _valid_soak(tmp_path)
    rows = telemetry.read_text(encoding="utf-8").splitlines()
    rows[200] = "not-json"
    del rows[300:304]
    telemetry.write_text("\n".join(rows) + "\n", encoding="utf-8")
    report = build_soak_report(**kwargs)
    assert report["status"] == "FAIL"
    errors = report["telemetry_integrity"]["errors"]
    assert "telemetry contains invalid JSON lines" in errors
    assert "telemetry contains an excessive sampling gap" in errors


def test_soak_rejects_valid_json_that_is_not_an_object(tmp_path: Path):
    kwargs, telemetry = _valid_soak(tmp_path)
    rows = telemetry.read_text(encoding="utf-8").splitlines()
    rows[50] = "[]"
    telemetry.write_text("\n".join(rows) + "\n", encoding="utf-8")
    report = build_soak_report(**kwargs)
    assert report["status"] == "FAIL"
    assert report["telemetry_integrity"]["invalid_json_lines"] == 1
