"""Input I8 pilot gate: real evidence requirements cannot be bypassed."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest


def _reset_pilot_tables(engine):
    from app.models.input_pilot import (
        InputPilot,
        InputPilotAcceptance,
        InputPilotAudit,
        InputPilotDailyMetric,
        InputPilotIncident,
    )

    tables = (
        InputPilotAcceptance.__table__,
        InputPilotAudit.__table__,
        InputPilotIncident.__table__,
        InputPilotDailyMetric.__table__,
        InputPilot.__table__,
    )
    for table in tables:
        table.drop(engine, checkfirst=True)
    for table in reversed(tables):
        table.create(engine, checkfirst=True)


def _configured_pilot(db, tenant_id, *, evidence_mode="live"):
    from app.models.input_pilot import InputPilot

    started = datetime.now(timezone.utc) - timedelta(days=13)
    journeys = [
        {
            "key": "nas_batch",
            "review_owner_id": str(uuid.uuid4()),
            "metadata_template": {"plant": "required"},
            "glossary_ref": "tenant://glossary/v1",
            "role_acl_ref": "tenant://acl/nas",
        },
        {
            "key": "long_audio",
            "review_owner_id": str(uuid.uuid4()),
            "metadata_template": {"line": "required"},
            "glossary_ref": "tenant://glossary/v1",
            "role_acl_ref": "tenant://acl/audio",
        },
    ]
    pilot = InputPilot(
        tenant_id=tenant_id,
        name="First tenant Input pilot",
        status="running",
        evidence_mode=evidence_mode,
        dedicated_environment=True,
        environment_evidence_sha256="e" * 64,
        data_processing_agreement_ref="contract://dpa/signed-v1",
        journeys=journeys,
        acceptance_config={},
        started_at=started,
        planned_end_at=started + timedelta(days=14),
        retrospective_sha256="b" * 64,
        retrospective_ref="report://pilot/retrospective-v1",
    )
    db.add(pilot)
    db.flush()
    return pilot


def _add_daily_metrics(db, pilot):
    from app.models.input_pilot import InputPilotDailyMetric

    start_date = pilot.started_at.date()
    for day in range(14):
        for journey in ("nas_batch", "long_audio"):
            db.add(
                InputPilotDailyMetric(
                    tenant_id=pilot.tenant_id,
                    pilot_id=pilot.id,
                    metric_date=start_date + timedelta(days=day),
                    journey_key=journey,
                    total_attempts=100,
                    successful_attempts=98,
                    retry_count=5,
                    manual_correction_count=8,
                    processing_p95_ms=120_000,
                    retrieval_checks=100,
                    cited_retrievals=95,
                    friction_count=1,
                    source_evidence_sha256="d" * 64,
                )
            )
    db.flush()


def _add_passing_audits(db, pilot):
    from app.models.input_pilot import InputPilotAudit

    for index, audit_type in enumerate(("quality", "security", "permission")):
        db.add(
            InputPilotAudit(
                tenant_id=pilot.tenant_id,
                pilot_id=pilot.id,
                audit_type=audit_type,
                status="pass",
                sample_size=30,
                findings=[],
                evidence_sha256=str(index + 1) * 64,
                audited_at=datetime.now(timezone.utc) - timedelta(minutes=3 - index),
            )
        )
    db.flush()


def _accept(db, pilot):
    from app.models.input_pilot import InputPilotAcceptance

    db.add(
        InputPilotAcceptance(
            tenant_id=pilot.tenant_id,
            pilot_id=pilot.id,
            decision="accepted",
            signer_name="Customer owner",
            signer_role="Plant manager",
            signed_document_sha256="a" * 64,
            signed_document_ref="contract://pilot/acceptance-v1",
            statement="Accepted against the agreed Input pilot SLO.",
            signed_at=datetime.now(timezone.utc),
        )
    )
    db.flush()


def test_complete_14_day_live_pilot_passes_only_after_signed_acceptance(test_engine):
    import app.models  # noqa: F401
    from app.db.base_class import Base
    from app.models.tenant import Tenant
    from app.services.input_pilot import evaluate_pilot_gate
    from sqlalchemy.orm import sessionmaker

    Base.metadata.create_all(test_engine)
    _reset_pilot_tables(test_engine)
    db = sessionmaker(bind=test_engine)()
    try:
        tenant = Tenant(id=uuid.uuid4(), name="I8 pass", plan="free", status="active")
        db.add(tenant)
        db.flush()
        pilot = _configured_pilot(db, tenant.id)
        _add_daily_metrics(db, pilot)
        _add_passing_audits(db, pilot)
        preflight = evaluate_pilot_gate(
            db, tenant_id=tenant.id, pilot_id=pilot.id, require_acceptance=False
        )
        assert preflight["status"] == "PASS"
        assert evaluate_pilot_gate(
            db, tenant_id=tenant.id, pilot_id=pilot.id
        )["status"] == "HOLD"
        _accept(db, pilot)
        result = evaluate_pilot_gate(db, tenant_id=tenant.id, pilot_id=pilot.id)
        assert result["status"] == "PASS"
        assert result["observation_days"] == 14
    finally:
        db.close()


def test_synthetic_mode_can_never_pass_field_pilot_gate(test_engine):
    import app.models  # noqa: F401
    from app.db.base_class import Base
    from app.models.tenant import Tenant
    from app.services.input_pilot import evaluate_pilot_gate
    from sqlalchemy.orm import sessionmaker

    Base.metadata.create_all(test_engine)
    _reset_pilot_tables(test_engine)
    db = sessionmaker(bind=test_engine)()
    try:
        tenant = Tenant(id=uuid.uuid4(), name="I8 synthetic", plan="free", status="active")
        db.add(tenant)
        db.flush()
        pilot = _configured_pilot(db, tenant.id, evidence_mode="synthetic")
        _add_daily_metrics(db, pilot)
        _add_passing_audits(db, pilot)
        _accept(db, pilot)
        result = evaluate_pilot_gate(db, tenant_id=tenant.id, pilot_id=pilot.id)
        assert result["status"] == "HOLD"
        assert "pilot evidence mode is not live" in result["errors"]
    finally:
        db.close()


def test_open_incident_and_latest_failed_audit_hold_gate(test_engine):
    import app.models  # noqa: F401
    from app.db.base_class import Base
    from app.models.input_pilot import InputPilotAudit, InputPilotIncident
    from app.models.tenant import Tenant
    from app.services.input_pilot import evaluate_pilot_gate
    from sqlalchemy.orm import sessionmaker

    Base.metadata.create_all(test_engine)
    _reset_pilot_tables(test_engine)
    db = sessionmaker(bind=test_engine)()
    try:
        tenant = Tenant(id=uuid.uuid4(), name="I8 hold", plan="free", status="active")
        db.add(tenant)
        db.flush()
        pilot = _configured_pilot(db, tenant.id)
        _add_daily_metrics(db, pilot)
        _add_passing_audits(db, pilot)
        _accept(db, pilot)
        incident = InputPilotIncident(
            tenant_id=tenant.id,
            pilot_id=pilot.id,
            severity="high",
            category="permission",
            near_miss=True,
            status="open",
            unauthorized_access=False,
            data_loss=False,
            false_completion=False,
            summary="Permission near miss",
            occurred_at=datetime.now(timezone.utc),
        )
        db.add(incident)
        db.add(
            InputPilotAudit(
                tenant_id=tenant.id,
                pilot_id=pilot.id,
                audit_type="permission",
                status="fail",
                sample_size=30,
                findings=[{"code": "permission_drift"}],
                evidence_sha256="f" * 64,
                audited_at=datetime.now(timezone.utc) + timedelta(minutes=1),
            )
        )
        db.flush()
        result = evaluate_pilot_gate(db, tenant_id=tenant.id, pilot_id=pilot.id)
        assert result["status"] == "HOLD"
        assert any("unresolved incident" in error for error in result["errors"])
        assert "missing passing audits: permission" in result["errors"]
    finally:
        db.close()


def test_tenant_cannot_read_another_tenants_pilot(test_engine):
    import app.models  # noqa: F401
    from app.db.base_class import Base
    from app.models.tenant import Tenant
    from app.services.input_pilot import evaluate_pilot_gate
    from sqlalchemy.orm import sessionmaker

    Base.metadata.create_all(test_engine)
    _reset_pilot_tables(test_engine)
    db = sessionmaker(bind=test_engine)()
    try:
        owner = Tenant(id=uuid.uuid4(), name="I8 owner", plan="free", status="active")
        stranger = Tenant(id=uuid.uuid4(), name="I8 stranger", plan="free", status="active")
        db.add_all([owner, stranger])
        db.flush()
        pilot = _configured_pilot(db, owner.id)
        with pytest.raises(LookupError):
            evaluate_pilot_gate(db, tenant_id=stranger.id, pilot_id=pilot.id)
    finally:
        db.close()


def test_gate_rejects_zero_sample_audit_unknown_journey_and_early_acceptance(test_engine):
    import app.models  # noqa: F401
    from app.db.base_class import Base
    from app.models.input_pilot import (
        InputPilotAcceptance,
        InputPilotAudit,
        InputPilotDailyMetric,
    )
    from app.models.tenant import Tenant
    from app.services.input_pilot import evaluate_pilot_gate
    from sqlalchemy.orm import sessionmaker

    Base.metadata.create_all(test_engine)
    _reset_pilot_tables(test_engine)
    db = sessionmaker(bind=test_engine)()
    try:
        tenant = Tenant(id=uuid.uuid4(), name="I8 invalid evidence", plan="free", status="active")
        db.add(tenant)
        db.flush()
        pilot = _configured_pilot(db, tenant.id)
        _add_daily_metrics(db, pilot)
        _add_passing_audits(db, pilot)
        zero_sample = db.query(InputPilotAudit).filter(
            InputPilotAudit.pilot_id == pilot.id,
            InputPilotAudit.audit_type == "quality",
        ).one()
        zero_sample.sample_size = 0
        db.add(
            InputPilotDailyMetric(
                tenant_id=tenant.id,
                pilot_id=pilot.id,
                metric_date=pilot.started_at.date(),
                journey_key="unconfigured",
                total_attempts=1,
                successful_attempts=1,
                retry_count=0,
                manual_correction_count=0,
                processing_p95_ms=1,
                retrieval_checks=1,
                cited_retrievals=1,
                friction_count=0,
                source_evidence_sha256="9" * 64,
            )
        )
        db.add(
            InputPilotAcceptance(
                tenant_id=tenant.id,
                pilot_id=pilot.id,
                decision="accepted",
                signer_name="Early signer",
                signer_role="Owner",
                signed_document_sha256="8" * 64,
                signed_document_ref="contract://pilot/too-early",
                statement="Signed before evidence completed.",
                signed_at=pilot.started_at,
            )
        )
        db.flush()

        result = evaluate_pilot_gate(db, tenant_id=tenant.id, pilot_id=pilot.id)

        assert result["status"] == "HOLD"
        assert "daily metrics contain unconfigured journeys: unconfigured" in result["errors"]
        assert any("passing audit has no sample" in error for error in result["errors"])
        assert "customer acceptance predates the final evidence day" in result["errors"]
    finally:
        db.close()
