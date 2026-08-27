"""Canonical versioned knowledge authority for every source and domain pack."""

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

KNOWLEDGE_UNIT_TYPES = (
    "narrative",
    "row",
    "field",
    "procedure",
    "knowhow",
    "entity",
    "compiled",
)


def _sql_values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class KnowledgeUnitRecord(Base):
    """Stable logical identity; content lives in immutable revisions."""

    __tablename__ = "knowledge_units"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    unit_key = Column(String(500), nullable=False)
    unit_type = Column(String(32), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    source_asset_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    source_resource_type = Column(String(100), nullable=False)
    source_resource_id = Column(String(500), nullable=False)
    current_revision = Column(Integer, nullable=False, default=0)
    status = Column(String(24), nullable=False, default="active")
    metadata_json = Column(JSON, nullable=False, default=dict)
    schema_version = Column(String(20), nullable=False, default="1.0")
    created_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    tombstoned_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_knowledge_units_tenant_id"),
        UniqueConstraint(
            "tenant_id", "unit_key", name="uq_knowledge_units_tenant_key"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "source_asset_id"],
            ["source_assets.tenant_id", "source_assets.id"],
            name="fk_knowledge_units_tenant_asset",
        ),
        CheckConstraint(
            f"unit_type IN ({_sql_values(KNOWLEDGE_UNIT_TYPES)})",
            name="ck_knowledge_units_type",
        ),
        CheckConstraint(
            "current_revision >= 0", name="ck_knowledge_units_current_revision"
        ),
        CheckConstraint(
            "status IN ('active', 'tombstoned')", name="ck_knowledge_units_status"
        ),
        Index(
            "ix_knowledge_units_tenant_type_status",
            "tenant_id",
            "unit_type",
            "status",
        ),
    )


class KnowledgeUnitRevision(Base):
    """Immutable, citable content and policy snapshot for a unit."""

    __tablename__ = "knowledge_unit_revisions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    unit_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    revision = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    content_hash = Column(String(71), nullable=False, index=True)
    authority_class = Column(String(50), nullable=False, default="primary_document")
    quality_state = Column(String(24), nullable=False, default="ready")
    risk_level = Column(String(24), nullable=False, default="normal")
    acl_snapshot = Column(JSON, nullable=False, default=dict)
    applicability_json = Column(JSON, nullable=False, default=dict)
    metadata_json = Column(JSON, nullable=False, default=dict)
    source_asset_revision_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    source_artifact_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    policy_revision = Column(Integer, nullable=False, default=1)
    schema_version = Column(String(20), nullable=False, default="1.0")
    effective_from = Column(DateTime(timezone=True), nullable=True)
    effective_to = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "id", name="uq_knowledge_unit_revisions_tenant_id"
        ),
        UniqueConstraint(
            "tenant_id",
            "unit_id",
            "revision",
            name="uq_knowledge_unit_revisions_unit_revision",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "unit_id"],
            ["knowledge_units.tenant_id", "knowledge_units.id"],
            name="fk_knowledge_unit_revisions_tenant_unit",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "source_asset_revision_id"],
            ["asset_revisions.tenant_id", "asset_revisions.id"],
            name="fk_knowledge_unit_revisions_tenant_asset_revision",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "source_artifact_id"],
            ["derived_artifacts.tenant_id", "derived_artifacts.id"],
            name="fk_knowledge_unit_revisions_tenant_artifact",
        ),
        CheckConstraint("revision >= 1", name="ck_knowledge_unit_revisions_revision"),
        CheckConstraint(
            "length(content_hash) IN (64, 71)",
            name="ck_knowledge_unit_revisions_hash",
        ),
        CheckConstraint(
            "quality_state IN ('provisional', 'review_required', 'ready', 'rejected')",
            name="ck_knowledge_unit_revisions_quality",
        ),
        CheckConstraint(
            "risk_level IN ('low', 'normal', 'high', 'critical')",
            name="ck_knowledge_unit_revisions_risk",
        ),
        CheckConstraint(
            "policy_revision >= 1", name="ck_knowledge_unit_revisions_policy"
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_from IS NULL OR effective_to > effective_from",
            name="ck_knowledge_unit_revisions_effective_period",
        ),
        Index(
            "ix_knowledge_unit_revisions_tenant_quality_created",
            "tenant_id",
            "quality_state",
            "created_at",
        ),
    )


class KnowledgeUnitRelease(Base):
    """Versioned release authority for tenant-wide or KB-scoped knowledge."""

    __tablename__ = "knowledge_unit_releases"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    release_key = Column(String(500), nullable=False)
    revision = Column(Integer, nullable=False)
    scope_kind = Column(String(32), nullable=False, default="tenant")
    scope_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    scope_revision_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    status = Column(String(24), nullable=False, default="candidate")
    policy_revision = Column(Integer, nullable=False, default=1)
    manifest_hash = Column(String(64), nullable=True)
    gate_evidence = Column(JSON, nullable=False, default=dict)
    created_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    activated_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "id", name="uq_knowledge_unit_releases_tenant_id"
        ),
        UniqueConstraint(
            "tenant_id",
            "release_key",
            "revision",
            name="uq_knowledge_unit_releases_key_revision",
        ),
        CheckConstraint("revision >= 1", name="ck_knowledge_unit_releases_revision"),
        CheckConstraint(
            "scope_kind IN ('tenant', 'knowledge_base')",
            name="ck_knowledge_unit_releases_scope_kind",
        ),
        CheckConstraint(
            "(scope_kind = 'tenant' AND scope_id IS NULL AND scope_revision_id IS NULL) OR "
            "(scope_kind = 'knowledge_base' AND scope_id IS NOT NULL "
            "AND scope_revision_id IS NOT NULL)",
            name="ck_knowledge_unit_releases_scope",
        ),
        CheckConstraint(
            "status IN ('candidate', 'active', 'retired', 'rejected')",
            name="ck_knowledge_unit_releases_status",
        ),
        CheckConstraint(
            "policy_revision >= 1", name="ck_knowledge_unit_releases_policy"
        ),
        Index(
            "uq_knowledge_unit_releases_active_key",
            "tenant_id",
            "release_key",
            unique=True,
            postgresql_where=(status == "active"),
            sqlite_where=(status == "active"),
        ),
    )


class KnowledgeUnitReleaseMembership(Base):
    """Immutable unit revision membership in a governed release."""

    __tablename__ = "knowledge_unit_release_memberships"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    release_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    unit_revision_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    acl_snapshot = Column(JSON, nullable=False, default=dict)
    policy_revision = Column(Integer, nullable=False, default=1)
    status = Column(String(24), nullable=False, default="active")
    added_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    activated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    retired_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "id", name="uq_knowledge_unit_memberships_tenant_id"
        ),
        UniqueConstraint(
            "tenant_id",
            "release_id",
            "unit_revision_id",
            name="uq_knowledge_unit_memberships_release_revision",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "release_id"],
            ["knowledge_unit_releases.tenant_id", "knowledge_unit_releases.id"],
            name="fk_knowledge_unit_memberships_tenant_release",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "unit_revision_id"],
            ["knowledge_unit_revisions.tenant_id", "knowledge_unit_revisions.id"],
            name="fk_knowledge_unit_memberships_tenant_revision",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "policy_revision >= 1", name="ck_knowledge_unit_memberships_policy"
        ),
        CheckConstraint(
            "status IN ('active', 'retired')",
            name="ck_knowledge_unit_memberships_status",
        ),
        Index(
            "ix_knowledge_unit_memberships_release_status",
            "release_id",
            "status",
        ),
    )
