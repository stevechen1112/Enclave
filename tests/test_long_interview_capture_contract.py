"""Contract checks for the durable long-form interview workflow.

These are intentionally database-free so they can run in CI environments that
only lint the application package.  Full mobile/network acceptance is covered
by the rollout plan and requires real devices.
"""
from datetime import datetime, timezone


def test_long_interview_models_are_loaded_into_metadata():
    import app.models  # noqa: F401
    from app.db.base_class import Base

    assert "mka_knowledge_capture_sessions" in Base.metadata.tables
    assert "mka_knowledge_capture_chunks" in Base.metadata.tables
    assert "mka_knowledge_capture_transcript_segments" in Base.metadata.tables
    constraints = Base.metadata.tables["mka_knowledge_capture_chunks"].constraints
    assert any(getattr(item, "name", "") == "uq_mka_capture_chunk_sequence" for item in constraints)


def test_long_interview_api_exposes_resumable_lifecycle_routes():
    from app.main import app

    paths = set(app.openapi()["paths"])
    assert "/api/v1/knowledge/captures" in paths
    assert "/api/v1/knowledge/captures/policy" in paths
    assert "/api/v1/knowledge/captures/{session_id}/chunks" in paths
    assert "/api/v1/knowledge/captures/{session_id}/complete" in paths
    assert "/api/v1/knowledge/captures/{session_id}/retry" in paths
    assert "/api/v1/knowledge/captures/{session_id}/transcript" in paths


def test_capture_is_core_and_not_owned_by_mka_pack():
    from pathlib import Path

    from app.main import app

    core_paths = set(app.openapi()["paths"])
    assert "/api/v1/knowledge/captures" in core_paths
    pack_source = (
        Path(__file__).resolve().parents[1] / "app" / "packs" / "mka" / "api.py"
    ).read_text(encoding="utf-8")
    assert "knowledge_capture" not in pack_source


def test_capture_status_response_does_not_expose_transcript_unless_requested():
    from app.api.v1.endpoints.knowledge_capture import _session_to_dict
    from app.models.mka import KnowledgeCaptureSession

    row = KnowledgeCaptureSession(
        id="00000000-0000-0000-0000-000000000001",
        title="換模訪談",
        status="ready_for_review",
        transcript="敏感逐字稿",
        received_chunks=2,
        total_duration_ms=60_000,
        created_at=datetime.now(timezone.utc),
    )
    assert "transcript" not in _session_to_dict(row)
    assert _session_to_dict(row, include_transcript=True)["transcript"] == "敏感逐字稿"


def test_long_interview_worker_is_registered_with_celery():
    from app.tasks.input_capture_tasks import transcribe_knowledge_capture

    assert transcribe_knowledge_capture.name == "tasks.transcribe_knowledge_capture"
