"""Domain-neutral knowledge execution models.

These models extend the existing KB, document-version and knowledge-gap models.
They intentionally do not duplicate those aggregates: immutable memberships point
at ``KnowledgeBaseRevision`` and ``DocumentVersion`` and runtime artifacts retain
their own provenance.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import relationship

from app.db.base_class import Base


class KnowledgeBaseRevisionDocument(Base):
    """Immutable membership of a document revision in a KB revision."""

    __tablename__ = "knowledge_base_revision_documents"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    kb_revision_id = Column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_base_revisions.id"),
        nullable=False,
        index=True,
    )
    document_id = Column(
        UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False, index=True
    )
    document_version_id = Column(
        UUID(as_uuid=True),
        ForeignKey("documentversions.id"),
        nullable=False,
        index=True,
    )
    document_revision = Column(Integer, nullable=False)
    content_hash = Column(String(128), nullable=False)
    acl_snapshot = Column(JSON, nullable=False, default=dict)
    policy_revision = Column(Integer, nullable=False, default=1)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "kb_revision_id", "document_id", name="uq_kb_revision_document"
        ),
        UniqueConstraint(
            "kb_revision_id",
            "document_version_id",
            name="uq_kb_revision_document_version",
        ),
    )


class PolicySnapshot(Base):
    __tablename__ = "knowledge_policy_snapshots"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    kb_id = Column(
        UUID(as_uuid=True), ForeignKey("knowledge_bases.id"), nullable=False, index=True
    )
    revision = Column(Integer, nullable=False)
    policy_json = Column(JSON, nullable=False, default=dict)
    policy_hash = Column(String(64), nullable=False)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    __table_args__ = (
        UniqueConstraint("kb_id", "revision", name="uq_kb_policy_snapshot"),
    )


class IndexArtifactRevision(Base):
    __tablename__ = "index_artifact_revisions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    kb_revision_id = Column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_base_revisions.id"),
        nullable=False,
        index=True,
    )
    artifact_type = Column(String(40), nullable=False)
    namespace = Column(String(255), nullable=False)
    version_manifest = Column(JSON, nullable=False, default=dict)
    artifact_hash = Column(String(64), nullable=False)
    status = Column(String(24), nullable=False, default="ready")
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    __table_args__ = (
        UniqueConstraint(
            "kb_revision_id", "artifact_type", "namespace", name="uq_kb_index_artifact"
        ),
    )


class RuntimeRelease(Base):
    __tablename__ = "knowledge_runtime_releases"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    kb_revision_id = Column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_base_revisions.id"),
        nullable=False,
        index=True,
    )
    image_digest = Column(String(255), nullable=False)
    frontend_image_digest = Column(String(255), nullable=True)
    deployment_manifest_id = Column(String(64), nullable=True)
    model_manifest = Column(JSON, nullable=False, default=dict)
    prompt_hash = Column(String(64), nullable=False)
    feature_flags = Column(JSON, nullable=False, default=dict)
    rollout_percent = Column(Integer, nullable=False, default=0)
    status = Column(String(24), nullable=False, default="candidate")
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DocumentProfile(Base):
    __tablename__ = "document_profiles"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    document_id = Column(
        UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False, index=True
    )
    document_revision = Column(Integer, nullable=False)
    format_family = Column(String(40), nullable=False)
    support_level = Column(String(24), nullable=False)
    language_profile = Column(JSON, nullable=False, default=dict)
    page_count = Column(Integer, nullable=True)
    structure_map = Column(JSON, nullable=False, default=dict)
    capability_readiness = Column(JSON, nullable=False, default=dict)
    warnings = Column(JSON, nullable=False, default=list)
    quality_score = Column(Float, nullable=True)
    answer_ready = Column(Boolean, nullable=False, default=False)
    profiler_version = Column(String(40), nullable=False)
    content_hash = Column(String(128), nullable=False)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    __table_args__ = (
        UniqueConstraint(
            "document_id", "document_revision", name="uq_document_profile_revision"
        ),
        Index("ix_document_profile_ready", "tenant_id", "answer_ready"),
    )


class StructuredTable(Base):
    __tablename__ = "knowledge_structured_tables"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    document_id = Column(
        UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False, index=True
    )
    document_revision = Column(Integer, nullable=False)
    worksheet = Column(String(255), nullable=True)
    table_key = Column(String(255), nullable=False)
    headers = Column(JSON, nullable=False, default=list)
    page = Column(Integer, nullable=True)
    bbox = Column(JSON, nullable=True)
    content_hash = Column(String(64), nullable=False)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "document_revision",
            "table_key",
            name="uq_structured_table_key",
        ),
    )


class StructuredRow(Base):
    __tablename__ = "knowledge_structured_rows"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    table_id = Column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_structured_tables.id"),
        nullable=False,
        index=True,
    )
    row_key = Column(String(255), nullable=False)
    row_number = Column(Integer, nullable=False)
    identity_json = Column(JSON, nullable=False, default=dict)
    row_hash = Column(String(64), nullable=False)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    fields = relationship(
        "StructuredField", cascade="all, delete-orphan", lazy="selectin"
    )
    __table_args__ = (
        UniqueConstraint("table_id", "row_key", name="uq_structured_row_key"),
    )


class StructuredField(Base):
    __tablename__ = "knowledge_structured_fields"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    row_id = Column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_structured_rows.id"),
        nullable=False,
        index=True,
    )
    field_name = Column(String(255), nullable=False)
    raw_value = Column(Text, nullable=True)
    normalized_value = Column(JSON, nullable=True)
    value_type = Column(String(32), nullable=False, default="text")
    unit = Column(String(32), nullable=True)
    confidence = Column(Float, nullable=False, default=1.0)
    bbox = Column(JSON, nullable=True)
    __table_args__ = (
        UniqueConstraint("row_id", "field_name", name="uq_structured_row_field"),
    )


class ProcedureGraph(Base):
    __tablename__ = "knowledge_procedure_graphs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    document_id = Column(
        UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False, index=True
    )
    document_revision = Column(Integer, nullable=False)
    title = Column(String(500), nullable=False)
    scope_json = Column(JSON, nullable=False, default=dict)
    risk_class = Column(String(24), nullable=False, default="normal")
    content_hash = Column(String(64), nullable=False)
    phases = relationship(
        "ProcedurePhase", cascade="all, delete-orphan", lazy="selectin"
    )
    __table_args__ = (
        UniqueConstraint(
            "document_id", "document_revision", "title", name="uq_procedure_graph"
        ),
    )


class ProcedurePhase(Base):
    __tablename__ = "knowledge_procedure_phases"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    graph_id = Column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_procedure_graphs.id"),
        nullable=False,
        index=True,
    )
    phase_key = Column(String(120), nullable=False)
    sequence = Column(Integer, nullable=False)
    actor = Column(String(255), nullable=True)
    instruction = Column(Text, nullable=False)
    required = Column(Boolean, nullable=False, default=True)
    completion_criteria = Column(Text, nullable=True)
    condition_json = Column(JSON, nullable=False, default=dict)
    exception_json = Column(JSON, nullable=False, default=dict)
    input_json = Column(JSON, nullable=False, default=list)
    output_json = Column(JSON, nullable=False, default=list)
    next_phase_keys = Column(JSON, nullable=False, default=list)
    source_ref = Column(JSON, nullable=False, default=dict)
    __table_args__ = (
        UniqueConstraint("graph_id", "phase_key", name="uq_procedure_phase"),
    )


class EntityRegistry(Base):
    __tablename__ = "knowledge_entities"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    entity_type = Column(String(80), nullable=False)
    canonical_key = Column(String(255), nullable=False)
    display_name = Column(String(500), nullable=False)
    attributes_json = Column(JSON, nullable=False, default=dict)
    status = Column(String(24), nullable=False, default="active")
    aliases = relationship("EntityAlias", cascade="all, delete-orphan", lazy="selectin")
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_knowledge_entities_tenant_id"),
        UniqueConstraint(
            "tenant_id", "entity_type", "canonical_key", name="uq_tenant_entity"
        ),
    )


class EntityAlias(Base):
    __tablename__ = "knowledge_entity_aliases"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    entity_id = Column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_entities.id"),
        nullable=False,
        index=True,
    )
    alias = Column(String(500), nullable=False)
    alias_normalized = Column(String(500), nullable=False)
    source_ref = Column(JSON, nullable=True)
    approved = Column(Boolean, nullable=False, default=False)
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "alias_normalized", "entity_id", name="uq_tenant_entity_alias"
        ),
    )


class KnowledgeRelease(Base):
    __tablename__ = "knowledge_releases"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    kb_id = Column(
        UUID(as_uuid=True), ForeignKey("knowledge_bases.id"), nullable=False, index=True
    )
    kb_revision_id = Column(
        UUID(as_uuid=True), ForeignKey("knowledge_base_revisions.id"), nullable=False
    )
    runtime_release_id = Column(
        UUID(as_uuid=True), ForeignKey("knowledge_runtime_releases.id"), nullable=True
    )
    status = Column(String(24), nullable=False, default="candidate")
    gate_evidence = Column(JSON, nullable=False, default=dict)
    activated_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RollbackPoint(Base):
    __tablename__ = "knowledge_rollback_points"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    kb_id = Column(
        UUID(as_uuid=True), ForeignKey("knowledge_bases.id"), nullable=False, index=True
    )
    from_release_id = Column(
        UUID(as_uuid=True), ForeignKey("knowledge_releases.id"), nullable=False
    )
    to_release_id = Column(
        UUID(as_uuid=True), ForeignKey("knowledge_releases.id"), nullable=False
    )
    reason = Column(Text, nullable=False)
    executed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EvaluationRun(Base):
    __tablename__ = "knowledge_evaluation_runs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True, index=True
    )
    split = Column(String(40), nullable=False)
    evaluation_key = Column(String(64), nullable=False, index=True)
    corpus_hash = Column(String(64), nullable=False)
    question_hash = Column(String(64), nullable=False)
    scoring_hash = Column(String(64), nullable=False)
    runtime_manifest = Column(JSON, nullable=False, default=dict)
    status = Column(String(24), nullable=False, default="running")
    first_run = Column(Boolean, nullable=False, default=True)
    baseline_run_id = Column(
        UUID(as_uuid=True), ForeignKey("knowledge_evaluation_runs.id"), nullable=True
    )
    summary_json = Column(JSON, nullable=False, default=dict)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        Index(
            "uq_knowledge_eval_first_run",
            "evaluation_key",
            unique=True,
            postgresql_where=(first_run.is_(True)),
        ),
    )


class EvaluationCaseResult(Base):
    __tablename__ = "knowledge_evaluation_case_results"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_evaluation_runs.id"),
        nullable=False,
        index=True,
    )
    case_id = Column(String(255), nullable=False)
    domain = Column(String(80), nullable=False)
    case_type = Column(String(80), nullable=False)
    verdict = Column(String(24), nullable=False)
    critical_error = Column(Boolean, nullable=False, default=False)
    metrics_json = Column(JSON, nullable=False, default=dict)
    evidence_digest = Column(String(64), nullable=True)
    __table_args__ = (
        UniqueConstraint("run_id", "case_id", name="uq_evaluation_run_case"),
    )


class EvaluationHumanReview(Base):
    __tablename__ = "knowledge_evaluation_human_reviews"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_result_id = Column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_evaluation_case_results.id"),
        nullable=False,
        index=True,
    )
    reviewer_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    original_verdict = Column(String(24), nullable=False)
    final_verdict = Column(String(24), nullable=False)
    reason = Column(Text, nullable=False)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class KnowledgeFreshnessState(Base):
    __tablename__ = "knowledge_freshness_states"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    document_id = Column(
        UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False, index=True
    )
    review_due_at = Column(DateTime(timezone=True), nullable=True)
    last_reviewed_at = Column(DateTime(timezone=True), nullable=True)
    upstream_sync_at = Column(DateTime(timezone=True), nullable=True)
    state = Column(String(24), nullable=False, default="current")
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    reasons = Column(JSON, nullable=False, default=list)
    __table_args__ = (
        UniqueConstraint("document_id", name="uq_document_freshness_state"),
    )


class LexicalIndexEntry(Base):
    """Incremental lexical projection; never rebuilt during a query."""

    __tablename__ = "knowledge_lexical_index"
    chunk_id = Column(
        UUID(as_uuid=True), ForeignKey("documentchunks.id"), primary_key=True
    )
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    document_id = Column(
        UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False, index=True
    )
    document_revision = Column(Integer, nullable=False)
    tokens = Column(ARRAY(String), nullable=False, default=list)
    token_count = Column(Integer, nullable=False)
    content_hash = Column(String(64), nullable=False)
    index_version = Column(String(32), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    __table_args__ = (
        Index("ix_knowledge_lexical_tokens_gin", "tokens", postgresql_using="gin"),
    )
