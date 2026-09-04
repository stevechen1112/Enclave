"""Tenant-safe operational lineage and entity projections for media v2.

These tables never become a second publication authority.  Source bytes remain
owned by AssetRevision and served knowledge remains governed by active
KnowledgeUnitRelease membership.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from app.db.base_class import Base


class MediaAnalysisRun(Base):
    __tablename__ = "media_analysis_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    asset_revision_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    run_key = Column(String(160), nullable=False)
    pipeline_version = Column(String(100), nullable=False)
    profile = Column(String(80), nullable=False)
    status = Column(String(32), nullable=False, default="queued")
    provider_manifest = Column(JSON, nullable=False, default=dict)
    configuration_json = Column(JSON, nullable=False, default=dict)
    configuration_hash = Column(String(64), nullable=False)
    checkpoint_json = Column(JSON, nullable=False, default=dict)
    quality_metrics = Column(JSON, nullable=False, default=dict)
    cost_metrics = Column(JSON, nullable=False, default=dict)
    failure_json = Column(JSON, nullable=False, default=dict)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_media_analysis_runs_tenant_id"),
        UniqueConstraint(
            "tenant_id",
            "asset_revision_id",
            "run_key",
            name="uq_media_analysis_run_key",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "asset_revision_id"],
            ["asset_revisions.tenant_id", "asset_revisions.id"],
            name="fk_media_analysis_run_revision",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "status IN ('queued','running','review_required','completed','degraded','failed','cancelled')",
            name="ck_media_analysis_run_status",
        ),
        Index(
            "ix_media_analysis_run_revision_status",
            "tenant_id",
            "asset_revision_id",
            "status",
        ),
    )


class ArtifactDerivationLink(Base):
    __tablename__ = "artifact_derivation_links"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    run_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    parent_artifact_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    child_artifact_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    relation_kind = Column(String(40), nullable=False, default="derived_from")
    metadata_json = Column(JSON, nullable=False, default=dict)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "run_id",
            "parent_artifact_id",
            "child_artifact_id",
            "relation_kind",
            name="uq_artifact_derivation_edge",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["media_analysis_runs.tenant_id", "media_analysis_runs.id"],
            name="fk_artifact_derivation_run",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "parent_artifact_id"],
            ["derived_artifacts.tenant_id", "derived_artifacts.id"],
            name="fk_artifact_derivation_parent",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "child_artifact_id"],
            ["derived_artifacts.tenant_id", "derived_artifacts.id"],
            name="fk_artifact_derivation_child",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "parent_artifact_id <> child_artifact_id",
            name="ck_artifact_derivation_not_self",
        ),
    )


class AssetEntityLink(Base):
    __tablename__ = "asset_entity_links"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    asset_revision_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    entity_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    link_kind = Column(String(50), nullable=False, default="mentions")
    status = Column(String(24), nullable=False, default="candidate")
    confidence = Column(Float, nullable=True)
    evidence_json = Column(JSON, nullable=False, default=list)
    projector_version = Column(String(100), nullable=False)
    source_hash = Column(String(64), nullable=False)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "asset_revision_id",
            "entity_id",
            "link_kind",
            "projector_version",
            "source_hash",
            name="uq_asset_entity_projection",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "asset_revision_id"],
            ["asset_revisions.tenant_id", "asset_revisions.id"],
            name="fk_asset_entity_revision",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "entity_id"],
            ["knowledge_entities.tenant_id", "knowledge_entities.id"],
            name="fk_asset_entity_entity",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "status IN ('candidate','approved','rejected','revoked')",
            name="ck_asset_entity_status",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_asset_entity_confidence",
        ),
        Index("ix_asset_entity_lookup", "tenant_id", "entity_id", "status"),
    )


class KnowledgeUnitEntityLink(Base):
    __tablename__ = "knowledge_unit_entity_links"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    unit_revision_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    entity_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    link_kind = Column(String(50), nullable=False, default="about")
    status = Column(String(24), nullable=False, default="candidate")
    confidence = Column(Float, nullable=True)
    evidence_json = Column(JSON, nullable=False, default=list)
    projector_version = Column(String(100), nullable=False)
    source_hash = Column(String(64), nullable=False)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "unit_revision_id",
            "entity_id",
            "link_kind",
            "projector_version",
            "source_hash",
            name="uq_knowledge_unit_entity_projection",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "unit_revision_id"],
            ["knowledge_unit_revisions.tenant_id", "knowledge_unit_revisions.id"],
            name="fk_unit_entity_revision",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "entity_id"],
            ["knowledge_entities.tenant_id", "knowledge_entities.id"],
            name="fk_knowledge_unit_entity_entity",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "status IN ('candidate','approved','rejected','revoked')",
            name="ck_knowledge_unit_entity_status",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_knowledge_unit_entity_confidence",
        ),
        Index("ix_knowledge_unit_entity_lookup", "tenant_id", "entity_id", "status"),
    )


class EntityRelationship(Base):
    __tablename__ = "entity_relationships"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    source_entity_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    target_entity_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    relation_kind = Column(String(80), nullable=False)
    status = Column(String(24), nullable=False, default="candidate")
    confidence = Column(Float, nullable=True)
    evidence_json = Column(JSON, nullable=False, default=list)
    projector_version = Column(String(100), nullable=False)
    source_hash = Column(String(64), nullable=False)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "source_entity_id",
            "target_entity_id",
            "relation_kind",
            "projector_version",
            "source_hash",
            name="uq_entity_relationship_projection",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "source_entity_id"],
            ["knowledge_entities.tenant_id", "knowledge_entities.id"],
            name="fk_entity_relationship_source",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "target_entity_id"],
            ["knowledge_entities.tenant_id", "knowledge_entities.id"],
            name="fk_entity_relationship_target",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "source_entity_id <> target_entity_id",
            name="ck_entity_relationship_not_self",
        ),
        CheckConstraint(
            "status IN ('candidate','approved','rejected','revoked')",
            name="ck_entity_relationship_status",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_entity_relationship_confidence",
        ),
        Index(
            "ix_entity_relationship_source", "tenant_id", "source_entity_id", "status"
        ),
        Index(
            "ix_entity_relationship_target", "tenant_id", "target_entity_id", "status"
        ),
    )
