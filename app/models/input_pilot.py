"""Tenant-scoped evidence ledger for the first Input pilot."""

from __future__ import annotations

import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from app.db.base_class import Base


class InputPilot(Base):
    __tablename__ = "input_pilots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    status = Column(String(24), nullable=False, default="draft")
    evidence_mode = Column(String(16), nullable=False, default="live")
    dedicated_environment = Column(Boolean, nullable=False, default=False)
    environment_evidence_sha256 = Column(String(64), nullable=True)
    data_processing_agreement_ref = Column(String(1000), nullable=True)
    journeys = Column(JSON, nullable=False, default=list)
    acceptance_config = Column(JSON, nullable=False, default=dict)
    started_at = Column(DateTime(timezone=True), nullable=True)
    planned_end_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    retrospective_sha256 = Column(String(64), nullable=True)
    retrospective_ref = Column(String(1000), nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_input_pilots_tenant_id"),
        CheckConstraint(
            "status IN ('draft','ready','running','hold','accepted','rejected')",
            name="ck_input_pilots_status",
        ),
        CheckConstraint(
            "evidence_mode IN ('live','synthetic')",
            name="ck_input_pilots_evidence_mode",
        ),
        Index("ix_input_pilots_tenant_status", "tenant_id", "status"),
    )


class InputPilotDailyMetric(Base):
    __tablename__ = "input_pilot_daily_metrics"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    pilot_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    metric_date = Column(Date, nullable=False)
    journey_key = Column(String(50), nullable=False)
    total_attempts = Column(Integer, nullable=False)
    successful_attempts = Column(Integer, nullable=False)
    retry_count = Column(Integer, nullable=False, default=0)
    manual_correction_count = Column(Integer, nullable=False, default=0)
    processing_p95_ms = Column(Integer, nullable=False)
    retrieval_checks = Column(Integer, nullable=False, default=0)
    cited_retrievals = Column(Integer, nullable=False, default=0)
    friction_count = Column(Integer, nullable=False, default=0)
    source_evidence_sha256 = Column(String(64), nullable=False)
    notes = Column(Text, nullable=True)
    recorded_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "pilot_id"],
            ["input_pilots.tenant_id", "input_pilots.id"],
            name="fk_input_pilot_metrics_tenant_pilot",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id", "pilot_id", "metric_date", "journey_key",
            name="uq_input_pilot_daily_metric",
        ),
        CheckConstraint(
            "total_attempts >= 0 AND successful_attempts >= 0 AND "
            "successful_attempts <= total_attempts AND retry_count >= 0 AND "
            "manual_correction_count >= 0 AND processing_p95_ms >= 0 AND "
            "retrieval_checks >= 0 AND cited_retrievals >= 0 AND "
            "cited_retrievals <= retrieval_checks AND friction_count >= 0",
            name="ck_input_pilot_daily_metric_values",
        ),
        Index("ix_input_pilot_metrics_pilot_date", "pilot_id", "metric_date"),
    )


class InputPilotIncident(Base):
    __tablename__ = "input_pilot_incidents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    pilot_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    severity = Column(String(16), nullable=False)
    category = Column(String(32), nullable=False)
    near_miss = Column(Boolean, nullable=False, default=False)
    status = Column(String(16), nullable=False, default="open")
    data_loss = Column(Boolean, nullable=False, default=False)
    unauthorized_access = Column(Boolean, nullable=False, default=False)
    false_completion = Column(Boolean, nullable=False, default=False)
    summary = Column(Text, nullable=False)
    root_cause = Column(Text, nullable=True)
    corrective_action = Column(Text, nullable=True)
    retrospective_sha256 = Column(String(64), nullable=True)
    occurred_at = Column(DateTime(timezone=True), nullable=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "pilot_id"],
            ["input_pilots.tenant_id", "input_pilots.id"],
            name="fk_input_pilot_incidents_tenant_pilot",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "severity IN ('low','medium','high','critical')",
            name="ck_input_pilot_incidents_severity",
        ),
        CheckConstraint(
            "status IN ('open','mitigated','resolved')",
            name="ck_input_pilot_incidents_status",
        ),
        Index("ix_input_pilot_incidents_pilot_status", "pilot_id", "status"),
    )


class InputPilotAudit(Base):
    __tablename__ = "input_pilot_audits"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    pilot_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    audit_type = Column(String(24), nullable=False)
    status = Column(String(16), nullable=False)
    sample_size = Column(Integer, nullable=False, default=0)
    findings = Column(JSON, nullable=False, default=list)
    evidence_sha256 = Column(String(64), nullable=False)
    auditor_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    audited_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "pilot_id"],
            ["input_pilots.tenant_id", "input_pilots.id"],
            name="fk_input_pilot_audits_tenant_pilot",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "audit_type IN ('quality','security','permission')",
            name="ck_input_pilot_audits_type",
        ),
        CheckConstraint(
            "status IN ('pending','pass','fail')",
            name="ck_input_pilot_audits_status",
        ),
        CheckConstraint("sample_size >= 0", name="ck_input_pilot_audits_sample_size"),
        Index("ix_input_pilot_audits_pilot_type", "pilot_id", "audit_type"),
    )


class InputPilotAcceptance(Base):
    __tablename__ = "input_pilot_acceptances"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    pilot_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    decision = Column(String(16), nullable=False)
    signer_name = Column(String(200), nullable=False)
    signer_role = Column(String(200), nullable=False)
    signed_document_sha256 = Column(String(64), nullable=False)
    signed_document_ref = Column(String(1000), nullable=False)
    statement = Column(Text, nullable=False)
    signed_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "pilot_id"],
            ["input_pilots.tenant_id", "input_pilots.id"],
            name="fk_input_pilot_acceptance_tenant_pilot",
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "pilot_id", name="uq_input_pilot_acceptance"),
        CheckConstraint(
            "decision IN ('accepted','rejected')",
            name="ck_input_pilot_acceptance_decision",
        ),
    )
