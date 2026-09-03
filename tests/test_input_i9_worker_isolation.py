from __future__ import annotations

from pathlib import Path

from app.celery_app import celery_app


def _queue_for(task_name: str) -> str:
    route = celery_app.amqp.router.route({}, task_name)
    return route["queue"].name


def test_heavy_input_tasks_are_routed_away_from_core_queue():
    assert _queue_for("tasks.process_audio_asset") == "input.media"
    assert _queue_for("tasks.process_video_asset") == "input.media"
    assert _queue_for("tasks.transcribe_knowledge_capture") == "input.media"
    assert (
        _queue_for("app.tasks.document_tasks.process_document_task")
        == "input.document"
    )
    assert _queue_for("app.tasks.document_tasks.process_url_task") == "input.document"
    assert _queue_for("tasks.process_outbox") == "celery"


def test_production_compose_serialises_input_with_resource_boundary():
    root = Path(__file__).resolve().parents[1]
    compose = (root / "docker-compose.prod.yml").read_text(encoding="utf-8")
    assert "worker-input:" in compose
    assert "--queues=input.media,input.document" in compose
    assert "--concurrency=1" in compose
    assert "--max-memory-per-child=1500000" in compose
    assert "OMP_THREAD_LIMIT=${MEDIA_PROCESSING_THREADS:-1}" in compose


def test_stale_reconciliation_is_periodically_scheduled():
    schedule = celery_app.conf.beat_schedule["reconcile-stale-ingestion"]
    assert schedule["task"] == "tasks.reconcile_stale_ingestion"
    assert schedule["schedule"] <= 300
