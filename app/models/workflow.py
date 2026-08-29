"""Domain-neutral Workflow Kernel persistence models.

Database table names retain their historical names where required for a
zero-migration ownership transfer. New code imports this module; app.models.mka
re-exports the former symbols only as a compatibility surface.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from app.db.base_class import Base


class FormDefinition(Base):
    """Versioned form schema owned by the Workflow Kernel."""

    __tablename__ = "form_definitions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True, index=True
    )
    form_key = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    schema_version = Column(String, default="1.0")
    json_schema = Column(JSON, default=dict)
    ui_schema = Column(JSON, default=dict)
    output_templates = Column(JSON, default=list)
    field_sources = Column(JSON, default=dict)
    active_template_id = Column(UUID(as_uuid=True), nullable=True)
    approval_policy_json = Column(JSON, default=dict)
    rule_set_id = Column(UUID(as_uuid=True), nullable=True)
    approval_policy_id = Column(UUID(as_uuid=True), nullable=True)
    status = Column(String, default="draft")
    effective_from = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint(
            "form_key",
            "tenant_id",
            "schema_version",
            name="uq_form_def_key_tenant_version",
        ),
    )


class FormInstance(Base):
    """Tenant-owned instance of a versioned form definition."""

    __tablename__ = "form_instances"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    form_definition_id = Column(
        UUID(as_uuid=True),
        ForeignKey("form_definitions.id"),
        nullable=False,
        index=True,
    )
    form_version = Column(String, default="1.0")
    module_key = Column(String, nullable=True)
    owner_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    status = Column(String, default="draft")
    record_version = Column(Integer, default=1, nullable=False)
    values_json = Column(JSON, default=dict)
    provenance_json = Column(JSON, default=dict)
    calculation_snapshot = Column(JSON, default=dict)
    validation_result = Column(JSON, default=dict)
    source_document_ids = Column(JSON, default=list)
    scene_context = Column(JSON, default=dict)
    approval_request_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "mka_approval_requests.id",
            name="fk_form_instance_approval_request",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    immutable_snapshot = Column(JSON, default=dict)
    export_artifacts = Column(JSON, default=list)
    approved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    finalized_at = Column(DateTime(timezone=True), nullable=True)


class RuleSet(Base):
    """Versioned deterministic rule definition."""

    __tablename__ = "rule_sets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True, index=True
    )
    rule_key = Column(String, nullable=False, index=True)
    version = Column(String, default="1.0")
    input_schema = Column(JSON, default=dict)
    output_schema = Column(JSON, default=dict)
    implementation_ref = Column(String, nullable=True)
    test_cases = Column(JSON, default=list)
    status = Column(String, default="draft")
    approved_by = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint(
            "rule_key", "tenant_id", "version", name="uq_rule_set_key_tenant_version"
        ),
    )


class ApprovalPolicy(Base):
    """Versioned approval policy shared by applications."""

    __tablename__ = "approval_policies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True, index=True
    )
    module_key = Column(String, nullable=True)
    object_type = Column(String, nullable=False)
    version = Column(String, default="1.0", nullable=False)
    status = Column(String, default="active")
    risk_level = Column(String, default="medium")
    steps = Column(JSON, default=list)
    timeout_policy = Column(JSON, default=dict)
    delegation_policy = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class WorkflowApprovalRequest(Base):
    """Approval request for a workflow object."""

    __tablename__ = "mka_approval_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    approval_policy_id = Column(
        UUID(as_uuid=True), ForeignKey("approval_policies.id"), nullable=True
    )
    object_type = Column(String, nullable=False)
    object_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    policy_version = Column(String, default="1.0")
    current_step = Column(Integer, default=0)
    record_version = Column(Integer, default=1, nullable=False)
    status = Column(String, default="pending")
    submitted_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    idempotency_key = Column(String, nullable=False)
    reviewers = Column(JSON, default=list)
    decision_log = Column(JSON, default=list)
    immutable_snapshot = Column(JSON, default=dict)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_mka_approval_idempotency"
        ),
    )


class TaskDefinition(Base):
    """Versioned task contract registered by an application."""

    __tablename__ = "mka_task_definitions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True, index=True
    )
    task_key = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    version = Column(String, default="1.0", nullable=False)
    status = Column(String, default="draft", nullable=False)
    handler_key = Column(String, nullable=False)
    module_key = Column(String, nullable=True, index=True)
    applicable_job_role_keys = Column(JSON, default=list)
    input_schema = Column(JSON, default=dict)
    required_capabilities = Column(JSON, default=list)
    approval_policy_id = Column(UUID(as_uuid=True), nullable=True)
    output_bindings = Column(JSON, default=list)
    risk_level = Column(String, default="low", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "task_key", "version", name="uq_mka_task_def_key_version"
        ),
    )


class TaskRun(Base):
    """Immutable-input execution record for a task definition."""

    __tablename__ = "mka_task_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    task_definition_id = Column(
        UUID(as_uuid=True), ForeignKey("mka_task_definitions.id"), nullable=False
    )
    task_key = Column(String, nullable=False, index=True)
    task_version = Column(String, nullable=False)
    idempotency_key = Column(String, nullable=False)
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    job_role_id = Column(UUID(as_uuid=True), nullable=True)
    module_key = Column(String, nullable=True)
    status = Column(String, default="draft", nullable=False, index=True)
    input_snapshot = Column(JSON, default=dict)
    resolved_context = Column(JSON, default=dict)
    field_sources = Column(JSON, default=dict)
    provenance = Column(JSON, default=dict)
    error = Column(JSON, nullable=True)
    output_refs = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_mka_task_run_idem"),
        Index("ix_mka_task_runs_tenant_status", "tenant_id", "status"),
    )


class TaskRunEvent(Base):
    """Append-only task execution event."""

    __tablename__ = "mka_task_run_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    run_id = Column(
        UUID(as_uuid=True), ForeignKey("mka_task_runs.id"), nullable=False, index=True
    )
    event_type = Column(String, nullable=False, index=True)
    actor_id = Column(UUID(as_uuid=True), nullable=True)
    payload = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_mka_task_run_events_tenant_type", "tenant_id", "event_type"),
    )


class FormTemplate(Base):
    """Tenant-owned output template for a form."""

    __tablename__ = "mka_form_templates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    form_key = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    format = Column(String, nullable=False)
    version = Column(String, default="1.0", nullable=False)
    storage_key = Column(String, nullable=False)
    placeholders = Column(JSON, default=list)
    field_mapping = Column(JSON, default=dict)
    status = Column(String, default="draft", nullable=False)
    effective_from = Column(DateTime(timezone=True), nullable=True)
    supersedes_id = Column(UUID(as_uuid=True), nullable=True)
    created_by = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "form_key", "version", name="uq_mka_form_template_version"
        ),
    )


# Compatibility symbol used by existing APIs and stored telemetry names.
MKAApprovalRequest = WorkflowApprovalRequest
