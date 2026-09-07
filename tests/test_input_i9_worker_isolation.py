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
    assert r'--destination=\"core@$$(hostname)\"' in compose
    assert r'--destination=\"input@$$(hostname)\"' in compose


def test_stale_reconciliation_is_periodically_scheduled():
    schedule = celery_app.conf.beat_schedule["reconcile-stale-ingestion"]
    assert schedule["task"] == "tasks.reconcile_stale_ingestion"
    assert schedule["schedule"] <= 300


def test_managed_deployments_sync_topology_and_require_input_worker():
    root = Path(__file__).resolve().parents[1]
    dockerignore = (root / ".dockerignore").read_text(encoding="utf-8")
    assert "!docker-compose.prod.yml" in dockerignore
    for workflow_name in ("deploy-production.yml", "deploy-staging.yml"):
        workflow = (root / ".github" / "workflows" / workflow_name).read_text(
            encoding="utf-8"
        )
        extract_idx = workflow.find(
            'docker cp "$MANIFEST_CONTAINER:/code/docker-compose.prod.yml"'
        )
        validate_idx = workflow.find(
            'docker compose -f "$MANIFEST_TMP" config --quiet'
        )
        replace_idx = workflow.find('mv "$MANIFEST_TMP" docker-compose.prod.yml')
        start_idx = workflow.find("up -d --no-build --remove-orphans")
        assert -1 not in (
            extract_idx,
            validate_idx,
            replace_idx,
            start_idx,
        ), workflow_name
        assert extract_idx < validate_idx < replace_idx < start_idx, workflow_name
        assert "stop web worker worker-input worker-beat" in workflow
        assert "ps -q worker-input" in workflow
        assert "/opt/venv/bin/celery -A app.celery_app inspect ping" in workflow
        assert '--destination=\"input@$(hostname)\"' in workflow
        assert 'curl -fsSL http://localhost/release.json' in workflow
        if workflow_name == "deploy-production.yml":
            assert (
                'curl -fsSL -o /dev/null -w "%{http_code}" http://localhost/'
                in workflow
            )
        stop_idx = workflow.find("stop web worker worker-input worker-beat")
        drain_idx = workflow.find("INPUT_DRAIN_DEADLINE=")
        assert -1 < drain_idx < stop_idx, workflow_name
        assert 'active is not None and reserved is not None' in workflow
        assert 'queued == 0' in workflow
        assert 'INPUT_DRAINED" != "true' in workflow
