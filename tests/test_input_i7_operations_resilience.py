"""Input I7 admission, fairness, SLO, cost and reconciliation acceptance."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest


def _seed_revision(db, tenant_id, *, kind="document"):
    from app.models.asset import AssetRevision, SourceAsset

    asset = SourceAsset(
        tenant_id=tenant_id,
        asset_kind=kind,
        title=f"{kind} source",
        source_system="upload",
        data_classification="internal",
        acl_reference={},
        metadata_json={},
        current_revision=1,
        status="active",
    )
    db.add(asset)
    db.flush()
    revision = AssetRevision(
        tenant_id=tenant_id,
        asset_id=asset.id,
        revision=1,
        media_type="text/plain" if kind == "document" else f"{kind}/test",
        content_uri=f"memory://{asset.id}",
        content_hash=uuid.uuid4().hex * 2,
        ingestion_status="pending",
        metadata_json={},
    )
    db.add(revision)
    db.flush()
    return revision


def _seed_job(db, tenant_id, revision_id, *, index=0, status="queued", attempt=0):
    from app.models.ingestion import IngestionJob

    row = IngestionJob(
        tenant_id=tenant_id,
        asset_revision_id=revision_id,
        adapter_key="test",
        adapter_version="1",
        requested_capabilities=["extract_text"],
        idempotency_key=f"i7:{tenant_id}:{index}:{uuid.uuid4()}",
        status=status,
        phase=status,
        attempt=attempt,
        started_at=(
            datetime.now(timezone.utc) - timedelta(hours=2)
            if status == "running"
            else None
        ),
    )
    db.add(row)
    db.flush()
    return row


def test_tenant_admission_backpressure_is_independent(test_engine):
    import app.models  # noqa: F401
    from app.db.base_class import Base
    from app.models.tenant import Tenant
    from app.services.input_operations import admission_decision, onboarding_quota_template
    from sqlalchemy.orm import sessionmaker

    Base.metadata.create_all(test_engine)
    db = sessionmaker(bind=test_engine)()
    try:
        noisy = Tenant(id=uuid.uuid4(), name="I7 noisy", plan="free", status="active")
        quiet = Tenant(id=uuid.uuid4(), name="I7 quiet", plan="free", status="active")
        db.add_all([noisy, quiet])
        db.flush()
        rev = _seed_revision(db, noisy.id)
        limit = onboarding_quota_template("lite")["max_active_ingestion_jobs_per_tenant"]
        for index in range(limit):
            _seed_job(db, noisy.id, rev.id, index=index)
        assert admission_decision(db, tenant_id=noisy.id, profile="lite")["reason"] == "tenant_backpressure"
        assert admission_decision(db, tenant_id=quiet.id, profile="lite")["allowed"] is True
    finally:
        db.close()


def test_fair_scheduler_round_robins_tenants(test_engine):
    import app.models  # noqa: F401
    from app.db.base_class import Base
    from app.models.tenant import Tenant
    from app.services.input_operations import fair_job_order
    from sqlalchemy.orm import sessionmaker

    Base.metadata.create_all(test_engine)
    db = sessionmaker(bind=test_engine)()
    try:
        first = Tenant(id=uuid.uuid4(), name="I7 first", plan="free", status="active")
        second = Tenant(id=uuid.uuid4(), name="I7 second", plan="free", status="active")
        db.add_all([first, second])
        db.flush()
        first_rev = _seed_revision(db, first.id)
        second_rev = _seed_revision(db, second.id)
        for index in range(3):
            _seed_job(db, first.id, first_rev.id, index=index)
        _seed_job(db, second.id, second_rev.id, index=0)
        selected = fair_job_order(db, limit=5000)
        tenant_sequence = [
            row.tenant_id for row in selected if row.tenant_id in {first.id, second.id}
        ]
        # Jobs flushed in the same transaction can share created_at; UUID is
        # then the stable tie-breaker, so either tenant may lead the round.
        assert set(tenant_sequence[:2]) == {first.id, second.id}
        assert tenant_sequence[2:] == [first.id, first.id]
    finally:
        db.close()


def test_slo_dashboard_uses_real_metric_rows_and_p95(test_engine):
    import app.models  # noqa: F401
    from app.db.base_class import Base
    from app.models.tenant import Tenant
    from app.services.input_operations import input_slo_dashboard, record_input_metric
    from sqlalchemy.orm import sessionmaker

    Base.metadata.create_all(test_engine)
    db = sessionmaker(bind=test_engine)()
    try:
        tenant = Tenant(id=uuid.uuid4(), name="I7 metrics", plan="free", status="active")
        db.add(tenant)
        db.flush()
        for duration in (10, 20, 30, 40, 500):
            record_input_metric(
                db,
                tenant_id=tenant.id,
                journey="upload",
                phase="acknowledgement",
                workload_kind="document",
                outcome="success",
                duration_ms=duration,
            )
        dashboard = input_slo_dashboard(db, tenant_id=tenant.id, profile="standard")
        assert dashboard["evidence_state"] == "LIVE"
        assert dashboard["phases"]["acknowledgement"]["p95_ms"] == 500
        assert dashboard["sample_count"] == 5
    finally:
        db.close()


def test_metric_storage_failure_does_not_abort_business_transaction(test_engine):
    import app.models  # noqa: F401
    from app.db.base_class import Base
    from app.models.ingestion import InputOperationMetric
    from app.models.tenant import Tenant
    from app.services.input_operations import record_input_metric
    from sqlalchemy.orm import sessionmaker

    Base.metadata.create_all(test_engine)
    InputOperationMetric.__table__.drop(test_engine, checkfirst=True)
    db = sessionmaker(bind=test_engine)()
    tenant_id = uuid.uuid4()
    try:
        db.add(Tenant(id=tenant_id, name="I7 metric fallback", plan="free", status="active"))
        result = record_input_metric(
            db,
            tenant_id=tenant_id,
            journey="upload",
            phase="acknowledgement",
            workload_kind="document",
            outcome="success",
            duration_ms=10,
        )
        assert result is None
        db.commit()
        assert db.query(Tenant).filter(Tenant.id == tenant_id).count() == 1
    finally:
        db.close()
        InputOperationMetric.__table__.create(test_engine, checkfirst=True)


def test_reconciliation_requeues_then_dead_letters_without_loss(test_engine):
    import app.models  # noqa: F401
    from app.db.base_class import Base
    from app.models.ingestion import IngestionJob
    from app.models.outbox import DeadLetterEvent
    from app.models.tenant import Tenant
    from app.services.input_operations import reconcile_stale_ingestion_jobs
    from sqlalchemy.orm import sessionmaker

    Base.metadata.create_all(test_engine)
    db = sessionmaker(bind=test_engine)()
    try:
        tenant = Tenant(id=uuid.uuid4(), name="I7 reconcile", plan="free", status="active")
        db.add(tenant)
        db.flush()
        retry_revision = _seed_revision(db, tenant.id)
        exhausted_revision = _seed_revision(db, tenant.id)
        retry = _seed_job(
            db, tenant.id, retry_revision.id, index=1, status="running", attempt=1
        )
        exhausted = _seed_job(
            db, tenant.id, exhausted_revision.id, index=2, status="running", attempt=3
        )
        result = reconcile_stale_ingestion_jobs(
            db,
            tenant_id=tenant.id,
            stale_before=datetime.now(timezone.utc) - timedelta(minutes=30),
            max_attempts=3,
        )
        db.flush()
        assert result == {
            "scanned": 2,
            "requeued": 1,
            "dead_lettered": 1,
            "requeued_job_ids": [str(retry.id)],
        }
        assert db.query(IngestionJob).filter(IngestionJob.id == retry.id).one().status == "queued"
        assert db.query(IngestionJob).filter(IngestionJob.id == exhausted.id).one().status == "failed"
        assert retry_revision.ingestion_status == "queued"
        assert exhausted_revision.ingestion_status == "failed"
        assert exhausted.error["retryable"] is False
        assert db.query(DeadLetterEvent).filter(
            DeadLetterEvent.original_event_id == exhausted.id
        ).count() == 1
    finally:
        db.close()


def test_capacity_estimator_is_explicitly_non_committal():
    from app.services.input_operations import estimate_capacity

    result = estimate_capacity(
        ingest_jobs_per_hour=25,
        media_hours_per_day=1,
        storage_gb=100,
        audio_hours_per_month=10,
        video_hours_per_month=5,
    )
    assert result["recommended_profile"] == "lite"
    assert result["modeled_monthly_input_cost_usd"] > 0
    assert "live I7 evidence" in result["claim_boundary"]


def test_orchestrator_enforces_admission_before_creating_job(
    test_engine, monkeypatch
):
    import app.models  # noqa: F401
    from app.composition.ingestion import build_ingestion_adapter_registry
    from app.db.base_class import Base
    from app.models.ingestion import IngestionJob
    from app.models.tenant import Tenant
    from app.services.ingestion_orchestrator import (
        IngestionBackpressure,
        IngestionOrchestrator,
    )
    from sqlalchemy.orm import sessionmaker

    Base.metadata.create_all(test_engine)
    db = sessionmaker(bind=test_engine)()
    try:
        tenant = Tenant(id=uuid.uuid4(), name="I7 reject", plan="free", status="active")
        db.add(tenant)
        db.flush()
        revision = _seed_revision(db, tenant.id)
        monkeypatch.setattr(
            "app.services.input_operations.admission_decision",
            lambda *_args, **_kwargs: {
                "allowed": False,
                "reason": "tenant_backpressure",
                "retry_after_seconds": 30,
            },
        )
        with pytest.raises(IngestionBackpressure):
            IngestionOrchestrator(build_ingestion_adapter_registry()).ensure_job(
                db,
                tenant_id=tenant.id,
                asset_revision_id=revision.id,
                capabilities=("extract_text",),
            )
        assert db.query(IngestionJob).filter(
            IngestionJob.tenant_id == tenant.id
        ).count() == 0
    finally:
        db.close()
