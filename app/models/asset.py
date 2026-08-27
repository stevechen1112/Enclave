"""Canonical multi-modal source asset persistence models.

SourceAsset is a stable logical identity. AssetRevision is immutable source
content. DerivedArtifact and EvidenceSpan preserve processor lineage and exact
source coordinates. Every child relationship includes tenant_id in its foreign
key so an application bug cannot create a cross-tenant lineage edge.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    Float,
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

ASSET_KINDS = (
    "document",
    "spreadsheet",
    "image",
    "audio",
    "video",
    "email",
    "web_page",
    "dataset",
    "external_record",
)

ARTIFACT_KINDS = (
    "extracted_text",
    "layout_page",
    "ocr_region",
    "table",
    "transcript_segment",
    "keyframe",
    "video_scene",
    "audio_event",
    "speaker_turn",
    "action_event",
    "equipment_state",
    "timeline_alignment",
    "sop_conflict_report",
    "procedure_candidate",
    "entity_candidate",
)

LOCATOR_KINDS = (
    "document",
    "table",
    "image",
    "audio",
    "video",
    "external_record",
)


def _sql_values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class SourceAsset(Base):
    """Stable logical identity for any tenant-owned knowledge source."""

    __tablename__ = "source_assets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    asset_kind = Column(String(32), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    source_system = Column(String(100), nullable=False, default="upload")
    source_record_id = Column(String(500), nullable=True)
    data_classification = Column(String(50), nullable=False, default="internal")
    acl_reference = Column(JSON, nullable=False, default=dict)
    metadata_json = Column(JSON, nullable=False, default=dict)
    current_revision = Column(Integer, nullable=False, default=0)
    status = Column(String(32), nullable=False, default="pending")
    schema_version = Column(String(20), nullable=False, default="1.0")
    created_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    captured_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    tombstoned_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_source_assets_tenant_id"),
        CheckConstraint(
            f"asset_kind IN ({_sql_values(ASSET_KINDS)})",
            name="ck_source_assets_kind",
        ),
        CheckConstraint(
            "current_revision >= 0", name="ck_source_assets_current_revision"
        ),
        CheckConstraint(
            "source_system = 'upload' OR source_record_id IS NOT NULL",
            name="ck_source_assets_connector_identity",
        ),
        Index(
            "uq_source_assets_external_identity_active",
            "tenant_id",
            "source_system",
            "source_record_id",
            unique=True,
            postgresql_where=(source_record_id.isnot(None) & tombstoned_at.is_(None)),
        ),
        Index(
            "ix_source_assets_tenant_kind_status",
            "tenant_id",
            "asset_kind",
            "status",
        ),
    )


class AssetRevision(Base):
    """Immutable bytes or immutable manifest for one source asset revision."""

    __tablename__ = "asset_revisions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    asset_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    revision = Column(Integer, nullable=False)
    media_type = Column(String(255), nullable=False)
    content_uri = Column(Text, nullable=False)
    content_hash = Column(String(71), nullable=False, index=True)
    external_version = Column(String(255), nullable=True)
    byte_size = Column(BigInteger, nullable=True)
    duration_ms = Column(BigInteger, nullable=True)
    effective_from = Column(DateTime(timezone=True), nullable=True)
    effective_to = Column(DateTime(timezone=True), nullable=True)
    ingestion_status = Column(String(32), nullable=False, default="pending")
    retention_policy = Column(JSON, nullable=False, default=dict)
    metadata_json = Column(JSON, nullable=False, default=dict)
    schema_version = Column(String(20), nullable=False, default="1.0")
    supersedes_revision_id = Column(UUID(as_uuid=True), nullable=True)
    created_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_asset_revisions_tenant_id"),
        UniqueConstraint(
            "tenant_id",
            "asset_id",
            "id",
            name="uq_asset_revisions_tenant_asset_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "asset_id",
            "revision",
            name="uq_asset_revisions_asset_revision",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "asset_id"],
            ["source_assets.tenant_id", "source_assets.id"],
            name="fk_asset_revisions_tenant_asset",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "asset_id", "supersedes_revision_id"],
            [
                "asset_revisions.tenant_id",
                "asset_revisions.asset_id",
                "asset_revisions.id",
            ],
            name="fk_asset_revisions_same_asset_predecessor",
        ),
        CheckConstraint("revision >= 1", name="ck_asset_revisions_revision"),
        CheckConstraint(
            "length(content_hash) IN (64, 71)",
            name="ck_asset_revisions_hash_length",
        ),
        CheckConstraint(
            "length(content_uri) > 0 AND length(media_type) > 2",
            name="ck_asset_revisions_content_identity",
        ),
        CheckConstraint(
            "byte_size IS NULL OR byte_size >= 0", name="ck_asset_revisions_size"
        ),
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_asset_revisions_duration",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_from IS NULL OR effective_to > effective_from",
            name="ck_asset_revisions_effective_period",
        ),
        Index(
            "ix_asset_revisions_tenant_asset_created",
            "tenant_id",
            "asset_id",
            "created_at",
        ),
    )


class DerivedArtifact(Base):
    """Immutable processor output derived from one asset revision."""

    __tablename__ = "derived_artifacts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    asset_revision_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    artifact_kind = Column(String(50), nullable=False, index=True)
    content_hash = Column(String(71), nullable=False, index=True)
    provider = Column(String(100), nullable=False)
    provider_version = Column(String(100), nullable=False)
    quality_state = Column(String(32), nullable=False, default="provisional")
    confidence = Column(Float, nullable=True)
    content = Column(Text, nullable=True)
    artifact_uri = Column(Text, nullable=True)
    metadata_json = Column(JSON, nullable=False, default=dict)
    schema_version = Column(String(20), nullable=False, default="1.0")
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_derived_artifacts_tenant_id"),
        UniqueConstraint(
            "tenant_id",
            "id",
            "asset_revision_id",
            name="uq_derived_artifacts_tenant_id_revision",
        ),
        UniqueConstraint(
            "tenant_id",
            "asset_revision_id",
            "artifact_kind",
            "provider",
            "provider_version",
            "content_hash",
            name="uq_derived_artifacts_identity",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "asset_revision_id"],
            ["asset_revisions.tenant_id", "asset_revisions.id"],
            name="fk_derived_artifacts_tenant_revision",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            f"artifact_kind IN ({_sql_values(ARTIFACT_KINDS)})",
            name="ck_derived_artifacts_kind",
        ),
        CheckConstraint(
            "length(content_hash) IN (64, 71)",
            name="ck_derived_artifacts_hash_length",
        ),
        CheckConstraint(
            "quality_state IN ('provisional', 'review_required', 'ready', 'rejected')",
            name="ck_derived_artifacts_quality_state",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_derived_artifacts_confidence",
        ),
        CheckConstraint(
            "content IS NOT NULL OR artifact_uri IS NOT NULL",
            name="ck_derived_artifacts_payload",
        ),
        Index(
            "ix_derived_artifacts_revision_kind_quality",
            "asset_revision_id",
            "artifact_kind",
            "quality_state",
        ),
    )


class EvidenceSpan(Base):
    """Typed location that traces an artifact back to exact source evidence."""

    __tablename__ = "evidence_spans"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    artifact_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    asset_revision_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    locator_kind = Column(String(32), nullable=False)
    page = Column(Integer, nullable=True)
    section = Column(String(500), nullable=True)
    bbox = Column(JSON, nullable=True)
    coordinate_space = Column(String(20), nullable=True)
    worksheet = Column(String(255), nullable=True)
    table_name = Column(String(255), nullable=True)
    row_number = Column(Integer, nullable=True)
    column_name = Column(String(100), nullable=True)
    cell_range = Column(String(100), nullable=True)
    start_ms = Column(BigInteger, nullable=True)
    end_ms = Column(BigInteger, nullable=True)
    speaker = Column(String(255), nullable=True)
    frame_index = Column(BigInteger, nullable=True)
    track_id = Column(String(255), nullable=True)
    source_system = Column(String(100), nullable=True)
    source_record_id = Column(String(500), nullable=True)
    field_path = Column(String(1000), nullable=True)
    schema_version = Column(String(20), nullable=False, default="1.0")
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "artifact_id", "asset_revision_id"],
            [
                "derived_artifacts.tenant_id",
                "derived_artifacts.id",
                "derived_artifacts.asset_revision_id",
            ],
            name="fk_evidence_spans_artifact_revision",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            f"locator_kind IN ({_sql_values(LOCATOR_KINDS)})",
            name="ck_evidence_spans_locator_kind",
        ),
        CheckConstraint(
            "coordinate_space IS NULL OR coordinate_space IN ('normalized', 'pixel')",
            name="ck_evidence_spans_coordinate_space",
        ),
        CheckConstraint(
            "bbox IS NULL OR coordinate_space IS NOT NULL",
            name="ck_evidence_spans_bbox_space",
        ),
        CheckConstraint("page IS NULL OR page >= 1", name="ck_evidence_spans_page"),
        CheckConstraint(
            "row_number IS NULL OR row_number >= 1", name="ck_evidence_spans_row"
        ),
        CheckConstraint(
            "frame_index IS NULL OR frame_index >= 0",
            name="ck_evidence_spans_frame",
        ),
        CheckConstraint(
            "(start_ms IS NULL AND end_ms IS NULL) OR "
            "(start_ms >= 0 AND end_ms > start_ms)",
            name="ck_evidence_spans_time_range",
        ),
        CheckConstraint(
            "(locator_kind = 'document' AND (page IS NOT NULL OR section IS NOT NULL)) OR "
            "(locator_kind = 'table' AND (worksheet IS NOT NULL OR table_name IS NOT NULL) "
            "AND (row_number IS NOT NULL OR column_name IS NOT NULL OR cell_range IS NOT NULL)) OR "
            "(locator_kind = 'image' AND (bbox IS NOT NULL OR section IS NOT NULL)) OR "
            "(locator_kind = 'audio' AND start_ms IS NOT NULL) OR "
            "(locator_kind = 'video' AND (start_ms IS NOT NULL OR frame_index IS NOT NULL)) OR "
            "(locator_kind = 'external_record' AND source_system IS NOT NULL "
            "AND source_record_id IS NOT NULL)",
            name="ck_evidence_spans_locator_payload",
        ),
        Index(
            "ix_evidence_spans_revision_locator",
            "asset_revision_id",
            "locator_kind",
        ),
    )


class ArtifactReviewDecision(Base):
    """Immutable human decision that promotes or rejects a provisional artifact."""

    __tablename__ = "artifact_review_decisions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    artifact_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    asset_revision_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    decision = Column(String(20), nullable=False)
    notes = Column(Text, nullable=True)
    resolution_json = Column(JSON, nullable=False, default=dict)
    reviewer_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "artifact_id", name="uq_artifact_review_decision"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "artifact_id", "asset_revision_id"],
            [
                "derived_artifacts.tenant_id",
                "derived_artifacts.id",
                "derived_artifacts.asset_revision_id",
            ],
            name="fk_artifact_review_decision_artifact_revision",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "decision IN ('approved', 'rejected')",
            name="ck_artifact_review_decision_value",
        ),
        Index(
            "ix_artifact_review_tenant_revision_created",
            "tenant_id",
            "asset_revision_id",
            "created_at",
        ),
    )
