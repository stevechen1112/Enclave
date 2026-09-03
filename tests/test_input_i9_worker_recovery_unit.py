from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.composition.ingestion import build_ingestion_adapter_registry
from app.models.asset import AssetRevision, SourceAsset
from app.models.ingestion import IngestionJob, IngestionJobEvent, InputOperationMetric
from app.models.outbox import DeadLetterEvent
from app.models.mka import JobRole
from app.models.permission import Department
from app.models.tenant import Tenant
from app.models.user import User
from app.services.ingestion_orchestrator import IngestionOrchestrator
from app.services.input_operations import reconcile_stale_ingestion_jobs


def _database():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

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
        DeadLetterEvent.__table__,
    ):
        table.create(engine, checkfirst=True)
    return engine, sessionmaker(bind=engine)()


def _job(db, *, tenant_id, attempt: int):
    asset = SourceAsset(
        tenant_id=tenant_id,
        asset_kind="audio",
        title=f"audio-{attempt}",
        source_system="upload",
        current_revision=1,
        status="processing",
    )
    db.add(asset)
    db.flush()
    revision = AssetRevision(
        tenant_id=tenant_id,
        asset_id=asset.id,
        revision=1,
        media_type="audio/wav",
        content_uri=f"memory://{asset.id}",
        content_hash=uuid4().hex * 2,
        ingestion_status="processing",
    )
    db.add(revision)
    db.flush()
    job = IngestionJob(
        tenant_id=tenant_id,
        asset_revision_id=revision.id,
        adapter_key="core.long_interview_audio",
        adapter_version="1",
        requested_capabilities=["transcribe"],
        idempotency_key=f"recovery:{asset.id}",
        status="running",
        phase="audio_processing",
        attempt=attempt,
        started_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    db.add(job)
    db.flush()
    return asset, revision, job


def test_recovery_updates_job_revision_and_asset_as_one_projection(monkeypatch):
    engine, db = _database()
    monkeypatch.setattr(
        "app.services.ingestion_orchestrator.get_ingestion_orchestrator",
        lambda: IngestionOrchestrator(build_ingestion_adapter_registry()),
    )
    try:
        tenant = Tenant(name="I9 recovery")
        db.add(tenant)
        db.flush()
        retry_asset, retry_revision, retry_job = _job(
            db, tenant_id=tenant.id, attempt=1
        )
        failed_asset, failed_revision, failed_job = _job(
            db, tenant_id=tenant.id, attempt=3
        )

        result = reconcile_stale_ingestion_jobs(
            db,
            tenant_id=tenant.id,
            stale_before=datetime.now(timezone.utc) - timedelta(minutes=30),
            max_attempts=3,
        )
        db.flush()

        assert result["requeued_job_ids"] == [str(retry_job.id)]
        assert retry_job.status == "queued"
        assert retry_revision.ingestion_status == "queued"
        assert retry_asset.status == "processing"
        assert failed_job.status == "failed"
        assert failed_revision.ingestion_status == "failed"
        assert failed_asset.status == "failed"
        assert failed_job.error["retryable"] is False
        assert db.query(DeadLetterEvent).count() == 1
    finally:
        db.close()
        engine.dispose()
