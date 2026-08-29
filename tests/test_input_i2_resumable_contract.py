"""Input I2 transport contract and local spool fault checks."""
from __future__ import annotations

import random
import tempfile
from pathlib import Path
from uuid import uuid4


def test_upload_models_have_tenant_composite_boundaries():
    import app.models  # noqa: F401
    from app.db.base_class import Base

    sessions = Base.metadata.tables["upload_sessions"]
    parts = Base.metadata.tables["upload_parts"]
    assert any(item.name == "uq_upload_sessions_idempotency" for item in sessions.constraints)
    assert any(item.name == "fk_upload_parts_tenant_session" for item in parts.constraints)
    assert any(item.name == "uq_upload_parts_session_number" for item in parts.constraints)


def test_upload_api_exposes_complete_resume_lifecycle():
    from app.api.v1.endpoints.upload_sessions import router

    routes = {(route.path, frozenset(route.methods or [])) for route in router.routes}
    assert ("/knowledge/upload-sessions", frozenset({"POST"})) in routes
    assert ("/knowledge/upload-sessions/{session_id}", frozenset({"GET"})) in routes
    assert ("/knowledge/upload-sessions/{session_id}/parts/{part_number}", frozenset({"PUT"})) in routes
    assert ("/knowledge/upload-sessions/{session_id}/commit", frozenset({"POST"})) in routes
    assert ("/knowledge/upload-sessions/{session_id}", frozenset({"DELETE"})) in routes


def test_migration_enables_rls_for_both_transport_tables():
    migration = Path("app/db/migrations/versions/input_i2_resumable_upload_001.py").read_text(encoding="utf-8")
    assert '_rls("upload_sessions")' in migration
    assert '_rls("upload_parts")' in migration
    assert 'down_revision = "p5_cost_guardrails_001"' in migration


def test_local_multipart_randomized_arrival_order_preserves_exact_bytes(tmp_path):
    from app.services.storage import build_storage_key
    from app.services.storage.local import LocalFilesystemBackend

    rng = random.Random(20260829)
    backend = LocalFilesystemBackend(str(tmp_path))
    for _case in range(12):
        tenant_id, object_id = uuid4(), uuid4()
        key = build_storage_key(tenant_id, object_id, ".bin")
        parts = [rng.randbytes(rng.randint(1, 4096)) for _ in range(rng.randint(1, 8))]
        order = list(range(1, len(parts) + 1))
        rng.shuffle(order)
        upload_id = backend.create_multipart(key)
        etags = []
        for number in order:
            with tempfile.NamedTemporaryFile(delete=False) as source:
                source.write(parts[number - 1])
                source_path = source.name
            try:
                etags.append(
                    (number, backend.upload_part(key, upload_id, number, source_path))
                )
            finally:
                Path(source_path).unlink(missing_ok=True)
        backend.complete_multipart(key, upload_id, etags)
        assert backend.get_bytes(key) == b"".join(parts)
