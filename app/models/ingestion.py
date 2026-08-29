"""Common ingestion lifecycle persistence."""

from __future__ import annotations

import uuid

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
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


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    asset_revision_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    adapter_key = Column(String(150), nullable=False)
    adapter_version = Column(String(100), nullable=False)
    requested_capabilities = Column(JSON, nullable=False, default=list)
    idempotency_key = Column(String(500), nullable=False)
    status = Column(String(32), nullable=False, default="queued", index=True)
    phase = Column(String(100), nullable=False, default="queued")
    attempt = Column(Integer, nullable=False, default=0)
    quality_state = Column(String(32), nullable=False, default="provisional")
    readiness = Column(JSON, nullable=False, default=dict)
    error = Column(JSON, nullable=False, default=dict)
    correlation_id = Column(String(255), nullable=True, index=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_ingestion_jobs_tenant_id"),
        UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_ingestion_jobs_idempotency"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "asset_revision_id"],
            ["asset_revisions.tenant_id", "asset_revisions.id"],
            name="fk_ingestion_jobs_tenant_revision",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'review_required', 'ready', 'failed', "
            "'cancelled')",
            name="ck_ingestion_jobs_status",
        ),
        CheckConstraint("attempt >= 0", name="ck_ingestion_jobs_attempt"),
        CheckConstraint(
            "quality_state IN ('provisional', 'review_required', 'ready', 'rejected')",
            name="ck_ingestion_jobs_quality_state",
        ),
        Index(
            "ix_ingestion_jobs_tenant_status_created",
            "tenant_id",
            "status",
            "created_at",
        ),
    )


class IngestionJobEvent(Base):
    __tablename__ = "ingestion_job_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    job_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    sequence = Column(Integer, nullable=False)
    from_status = Column(String(32), nullable=True)
    to_status = Column(String(32), nullable=False)
    phase = Column(String(100), nullable=False)
    details = Column(JSON, nullable=False, default=dict)
    message = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "job_id"],
            ["ingestion_jobs.tenant_id", "ingestion_jobs.id"],
            name="fk_ingestion_job_events_tenant_job",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id",
            "job_id",
            "sequence",
            name="uq_ingestion_job_events_sequence",
        ),
        CheckConstraint("sequence >= 1", name="ck_ingestion_job_events_sequence"),
        Index("ix_ingestion_job_events_job_created", "job_id", "created_at"),
    )


class InputOperationMetric(Base):
    """Low-cardinality, tenant-scoped Input journey timing evidence."""

    __tablename__ = "input_operation_metrics"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    journey = Column(String(32), nullable=False)
    phase = Column(String(32), nullable=False)
    workload_kind = Column(String(32), nullable=False)
    outcome = Column(String(20), nullable=False)
    duration_ms = Column(Integer, nullable=False)
    correlation_id = Column(String(255), nullable=True, index=True)
    details = Column(JSON, nullable=False, default=dict)
    recorded_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "journey IN ('upload', 'batch', 'document', 'audio', 'video', 'connector')",
            name="ck_input_operation_metrics_journey",
        ),
        CheckConstraint(
            "phase IN ('acknowledgement', 'transfer', 'queue_wait', 'processing', 'review_readiness')",
            name="ck_input_operation_metrics_phase",
        ),
        CheckConstraint(
            "outcome IN ('success', 'failed', 'rejected', 'pending')",
            name="ck_input_operation_metrics_outcome",
        ),
        CheckConstraint(
            "duration_ms >= 0", name="ck_input_operation_metrics_duration"
        ),
        Index(
            "ix_input_operation_metrics_tenant_phase_recorded",
            "tenant_id",
            "phase",
            "recorded_at",
        ),
    )
