from __future__ import annotations

from io import StringIO
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.composition.ingestion import build_ingestion_adapter_registry
from app.models.asset import AssetRevision, SourceAsset
from app.models.ingestion import IngestionJob, IngestionJobEvent, InputOperationMetric
from app.models.mka import JobRole
from app.models.permission import Department
from app.models.tenant import Tenant
from app.models.user import User
from app.platform.ingestion import IngestionAdapterRegistry, IngestionRequest
from app.services.ingestion_orchestrator import (
    IngestionOrchestrator,
    InvalidIngestionTransition,
)


@pytest.fixture()
def ingestion_db():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    for table in (
        Tenant.__table__,
        Department.__table__,
        JobRole.__table__,
        User.__table__,
        SourceAsset.__table__,
        AssetRevision.__table__,
        IngestionJob.__table__,
        IngestionJobEvent.__table__,
        InputOperationMetric.__table__,
    ):
        table.create(engine, checkfirst=True)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _source(db, *, kind="document", media_type="application/pdf"):
    tenant = Tenant(name=f"tenant-{uuid4().hex[:6]}")
    db.add(tenant)
    db.flush()
    asset = SourceAsset(
        tenant_id=tenant.id,
        asset_kind=kind,
        title="source",
        source_system="upload",
        status="active",
        current_revision=1,
    )
    db.add(asset)
    db.flush()
    revision = AssetRevision(
        tenant_id=tenant.id,
        asset_id=asset.id,
        revision=1,
        media_type=media_type,
        content_uri="s3://bucket/source.bin",
        content_hash="a" * 64,
        ingestion_status="ready",
    )
    db.add(revision)
    db.flush()
    return tenant, asset, revision


def test_registry_routes_by_asset_kind_and_capability():
    registry = build_ingestion_adapter_registry()
    document = IngestionRequest(
        tenant_id="t",
        asset_id="a",
        asset_revision_id="r",
        asset_kind="document",
        media_type="application/pdf",
        content_uri="s3://bucket/a.pdf",
        requested_capabilities=("extract_text",),
    )
    audio = IngestionRequest(
        tenant_id="t",
        asset_id="a",
        asset_revision_id="r",
        asset_kind="audio",
        media_type="audio/webm",
        content_uri="capture://a",
        requested_capabilities=("transcribe", "timestamp"),
    )

    assert registry.select(document).adapter_key == "core.document"
    assert registry.select(audio).adapter_key == "core.long_interview_audio"


def test_orchestrator_idempotency_transitions_and_event_sequence(ingestion_db):
    tenant, _, revision = _source(ingestion_db)
    orchestrator = IngestionOrchestrator(build_ingestion_adapter_registry())
    job = orchestrator.ensure_job(
        ingestion_db,
        tenant_id=tenant.id,
        asset_revision_id=revision.id,
        capabilities=("extract_text",),
        idempotency_key="doc:1",
    )
    same = orchestrator.ensure_job(
        ingestion_db,
        tenant_id=tenant.id,
        asset_revision_id=revision.id,
        capabilities=("extract_text",),
        idempotency_key="doc:1",
    )
    orchestrator.transition(ingestion_db, job, to_status="running", phase="parsing")
    orchestrator.transition(
        ingestion_db,
        job,
        to_status="ready",
        phase="published",
        quality_state="ready",
        readiness={"search": True},
    )

    assert same.id == job.id
    assert job.attempt == 1
    assert job.status == "ready"
    assert [row.sequence for row in ingestion_db.query(IngestionJobEvent).all()] == [
        1,
        2,
        3,
    ]
    with pytest.raises(InvalidIngestionTransition):
        orchestrator.transition(ingestion_db, job, to_status="running", phase="illegal")


def test_failed_job_retry_increments_attempt(ingestion_db):
    tenant, _, revision = _source(ingestion_db)
    orchestrator = IngestionOrchestrator(build_ingestion_adapter_registry())
    job = orchestrator.ensure_job(
        ingestion_db,
        tenant_id=tenant.id,
        asset_revision_id=revision.id,
        capabilities=("extract_text",),
    )
    orchestrator.transition(ingestion_db, job, to_status="running", phase="parsing")
    orchestrator.fail(
        ingestion_db, job, code="parse_failed", message="failed", phase="parsing"
    )
    orchestrator.transition(ingestion_db, job, to_status="running", phase="parsing")

    assert job.status == "running"
    assert job.attempt == 2


def test_idempotency_key_rejects_different_capability_request(ingestion_db):
    tenant, _, revision = _source(ingestion_db)
    orchestrator = IngestionOrchestrator(build_ingestion_adapter_registry())
    orchestrator.ensure_job(
        ingestion_db,
        tenant_id=tenant.id,
        asset_revision_id=revision.id,
        capabilities=("extract_text",),
        idempotency_key="fixed",
    )

    with pytest.raises(ValueError, match="another ingestion request"):
        orchestrator.ensure_job(
            ingestion_db,
            tenant_id=tenant.id,
            asset_revision_id=revision.id,
            capabilities=("extract_text", "layout"),
            idempotency_key="fixed",
        )


def test_registry_rejects_descriptor_without_accepts():
    class Invalid:
        adapter_key = "invalid"
        adapter_version = "1"
        supported_asset_kinds = ("document",)
        capability_keys = ("extract_text",)
        execution_boundary = "local"

    with pytest.raises(ValueError, match="metadata"):
        IngestionAdapterRegistry([Invalid()])


def test_job_composite_fk_rejects_cross_tenant_revision(ingestion_db):
    _tenant_a, _, revision = _source(ingestion_db)
    tenant_b, _, _ = _source(ingestion_db)
    ingestion_db.add(
        IngestionJob(
            tenant_id=tenant_b.id,
            asset_revision_id=revision.id,
            adapter_key="core.document",
            adapter_version="1",
            requested_capabilities=["extract_text"],
            idempotency_key="bad",
        )
    )

    with pytest.raises(IntegrityError):
        ingestion_db.flush()


def test_phase_c_migration_renders_upgrade_and_downgrade():
    from app.db.migrations.versions import ingestion_job_c1_008 as migration

    upgrade_buffer = StringIO()
    context = MigrationContext.configure(
        url="postgresql://",
        opts={"as_sql": True, "output_buffer": upgrade_buffer},
    )
    with Operations.context(context):
        migration.upgrade()
    downgrade_buffer = StringIO()
    context = MigrationContext.configure(
        url="postgresql://",
        opts={"as_sql": True, "output_buffer": downgrade_buffer},
    )
    with Operations.context(context):
        migration.downgrade()

    assert "CREATE TABLE ingestion_jobs" in upgrade_buffer.getvalue()
    assert "ENABLE ROW LEVEL SECURITY" in upgrade_buffer.getvalue()
    assert "DROP TABLE ingestion_jobs" in downgrade_buffer.getvalue()


def test_legacy_workers_are_wired_to_common_ingestion_orchestrator():
    root = __import__("pathlib").Path(__file__).resolve().parents[1]
    document_worker = (root / "app" / "tasks" / "document_tasks.py").read_text(
        encoding="utf-8"
    )
    audio_worker = (root / "app" / "tasks" / "mka_tasks.py").read_text(encoding="utf-8")

    assert document_worker.count("get_ingestion_orchestrator") >= 4
    assert "document_capabilities" in document_worker
    assert "get_ingestion_orchestrator" in audio_worker
    assert "timestamped_evidence" in audio_worker
