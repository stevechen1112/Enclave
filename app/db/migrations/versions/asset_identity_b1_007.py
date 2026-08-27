"""Add canonical multi-modal asset identity and lineage tables.

Revision ID: asset_identity_b1_007
Revises: demo_tenant_boundary_k6_006
"""

from __future__ import annotations

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "asset_identity_b1_007"
down_revision: str | None = "demo_tenant_boundary_k6_006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_TABLES = (
    "source_assets",
    "asset_revisions",
    "derived_artifacts",
    "evidence_spans",
)

_TENANT_POLICY = """
CREATE POLICY tenant_isolation ON "{table}"
  USING (
    tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
    OR current_setting('app.bypass_rls', true) = 'on'
  )
  WITH CHECK (
    tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
    OR current_setting('app.bypass_rls', true) = 'on'
  )
"""


def _enable_rls() -> None:
    force = os.environ.get("RLS_ENFORCEMENT_ENABLED", "false").lower() == "true"
    for table in _TENANT_TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
        op.execute(_TENANT_POLICY.format(table=table))
        op.execute(
            f'ALTER TABLE "{table}" '
            f"{'FORCE' if force else 'NO FORCE'} ROW LEVEL SECURITY"
        )


def upgrade() -> None:
    op.create_table(
        "source_assets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column("asset_kind", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column(
            "source_system",
            sa.String(length=100),
            nullable=False,
            server_default="upload",
        ),
        sa.Column("source_record_id", sa.String(length=500), nullable=True),
        sa.Column(
            "data_classification",
            sa.String(length=50),
            nullable=False,
            server_default="internal",
        ),
        sa.Column("acl_reference", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("current_revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "status", sa.String(length=32), nullable=False, server_default="pending"
        ),
        sa.Column(
            "schema_version", sa.String(length=20), nullable=False, server_default="1.0"
        ),
        sa.Column(
            "created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.Column(
            "captured_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.Column("tombstoned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "id", name="uq_source_assets_tenant_id"),
        sa.CheckConstraint(
            "asset_kind IN ('document', 'spreadsheet', 'image', 'audio', 'video', "
            "'email', 'web_page', 'dataset', 'external_record')",
            name="ck_source_assets_kind",
        ),
        sa.CheckConstraint(
            "current_revision >= 0", name="ck_source_assets_current_revision"
        ),
        sa.CheckConstraint(
            "source_system = 'upload' OR source_record_id IS NOT NULL",
            name="ck_source_assets_connector_identity",
        ),
    )
    op.create_index("ix_source_assets_tenant_id", "source_assets", ["tenant_id"])
    op.create_index("ix_source_assets_asset_kind", "source_assets", ["asset_kind"])
    op.create_index("ix_source_assets_created_by", "source_assets", ["created_by"])
    op.create_index("ix_source_assets_captured_by", "source_assets", ["captured_by"])
    op.create_index(
        "ix_source_assets_tenant_kind_status",
        "source_assets",
        ["tenant_id", "asset_kind", "status"],
    )
    op.create_index(
        "uq_source_assets_external_identity_active",
        "source_assets",
        ["tenant_id", "source_system", "source_record_id"],
        unique=True,
        postgresql_where=sa.text(
            "source_record_id IS NOT NULL AND tombstoned_at IS NULL"
        ),
    )

    op.create_table(
        "asset_revisions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column("asset_id", UUID(as_uuid=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("media_type", sa.String(length=255), nullable=False),
        sa.Column("content_uri", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=71), nullable=False),
        sa.Column("external_version", sa.String(length=255), nullable=True),
        sa.Column("byte_size", sa.BigInteger(), nullable=True),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "ingestion_status",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("retention_policy", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "schema_version", sa.String(length=20), nullable=False, server_default="1.0"
        ),
        sa.Column(
            "supersedes_revision_id",
            UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_asset_revisions_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "asset_id",
            "id",
            name="uq_asset_revisions_tenant_asset_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "asset_id",
            "revision",
            name="uq_asset_revisions_asset_revision",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "asset_id"],
            ["source_assets.tenant_id", "source_assets.id"],
            name="fk_asset_revisions_tenant_asset",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "asset_id", "supersedes_revision_id"],
            [
                "asset_revisions.tenant_id",
                "asset_revisions.asset_id",
                "asset_revisions.id",
            ],
            name="fk_asset_revisions_same_asset_predecessor",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_asset_revisions_revision"),
        sa.CheckConstraint(
            "length(content_hash) IN (64, 71)",
            name="ck_asset_revisions_hash_length",
        ),
        sa.CheckConstraint(
            "length(content_uri) > 0 AND length(media_type) > 2",
            name="ck_asset_revisions_content_identity",
        ),
        sa.CheckConstraint(
            "byte_size IS NULL OR byte_size >= 0", name="ck_asset_revisions_size"
        ),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_asset_revisions_duration",
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_from IS NULL OR effective_to > effective_from",
            name="ck_asset_revisions_effective_period",
        ),
    )
    op.create_index("ix_asset_revisions_tenant_id", "asset_revisions", ["tenant_id"])
    op.create_index("ix_asset_revisions_asset_id", "asset_revisions", ["asset_id"])
    op.create_index(
        "ix_asset_revisions_content_hash", "asset_revisions", ["content_hash"]
    )
    op.create_index("ix_asset_revisions_created_by", "asset_revisions", ["created_by"])
    op.create_index(
        "ix_asset_revisions_tenant_asset_created",
        "asset_revisions",
        ["tenant_id", "asset_id", "created_at"],
    )

    op.create_table(
        "derived_artifacts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column("asset_revision_id", UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_kind", sa.String(length=50), nullable=False),
        sa.Column("content_hash", sa.String(length=71), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("provider_version", sa.String(length=100), nullable=False),
        sa.Column(
            "quality_state",
            sa.String(length=32),
            nullable=False,
            server_default="provisional",
        ),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("artifact_uri", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "schema_version", sa.String(length=20), nullable=False, server_default="1.0"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_derived_artifacts_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            "asset_revision_id",
            name="uq_derived_artifacts_tenant_id_revision",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "asset_revision_id",
            "artifact_kind",
            "provider",
            "provider_version",
            "content_hash",
            name="uq_derived_artifacts_identity",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "asset_revision_id"],
            ["asset_revisions.tenant_id", "asset_revisions.id"],
            name="fk_derived_artifacts_tenant_revision",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "artifact_kind IN ('extracted_text', 'layout_page', 'ocr_region', 'table', "
            "'transcript_segment', 'keyframe', 'video_scene', 'audio_event', "
            "'procedure_candidate', 'entity_candidate')",
            name="ck_derived_artifacts_kind",
        ),
        sa.CheckConstraint(
            "length(content_hash) IN (64, 71)",
            name="ck_derived_artifacts_hash_length",
        ),
        sa.CheckConstraint(
            "quality_state IN ('provisional', 'review_required', 'ready', 'rejected')",
            name="ck_derived_artifacts_quality_state",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_derived_artifacts_confidence",
        ),
        sa.CheckConstraint(
            "content IS NOT NULL OR artifact_uri IS NOT NULL",
            name="ck_derived_artifacts_payload",
        ),
    )
    op.create_index(
        "ix_derived_artifacts_tenant_id", "derived_artifacts", ["tenant_id"]
    )
    op.create_index(
        "ix_derived_artifacts_asset_revision_id",
        "derived_artifacts",
        ["asset_revision_id"],
    )
    op.create_index(
        "ix_derived_artifacts_artifact_kind", "derived_artifacts", ["artifact_kind"]
    )
    op.create_index(
        "ix_derived_artifacts_content_hash", "derived_artifacts", ["content_hash"]
    )
    op.create_index(
        "ix_derived_artifacts_revision_kind_quality",
        "derived_artifacts",
        ["asset_revision_id", "artifact_kind", "quality_state"],
    )

    op.create_table(
        "evidence_spans",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column("artifact_id", UUID(as_uuid=True), nullable=False),
        sa.Column("asset_revision_id", UUID(as_uuid=True), nullable=False),
        sa.Column("locator_kind", sa.String(length=32), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("section", sa.String(length=500), nullable=True),
        sa.Column("bbox", sa.JSON(), nullable=True),
        sa.Column("coordinate_space", sa.String(length=20), nullable=True),
        sa.Column("worksheet", sa.String(length=255), nullable=True),
        sa.Column("table_name", sa.String(length=255), nullable=True),
        sa.Column("row_number", sa.Integer(), nullable=True),
        sa.Column("column_name", sa.String(length=100), nullable=True),
        sa.Column("cell_range", sa.String(length=100), nullable=True),
        sa.Column("start_ms", sa.BigInteger(), nullable=True),
        sa.Column("end_ms", sa.BigInteger(), nullable=True),
        sa.Column("speaker", sa.String(length=255), nullable=True),
        sa.Column("frame_index", sa.BigInteger(), nullable=True),
        sa.Column("track_id", sa.String(length=255), nullable=True),
        sa.Column("source_system", sa.String(length=100), nullable=True),
        sa.Column("source_record_id", sa.String(length=500), nullable=True),
        sa.Column("field_path", sa.String(length=1000), nullable=True),
        sa.Column(
            "schema_version", sa.String(length=20), nullable=False, server_default="1.0"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "artifact_id", "asset_revision_id"],
            [
                "derived_artifacts.tenant_id",
                "derived_artifacts.id",
                "derived_artifacts.asset_revision_id",
            ],
            name="fk_evidence_spans_artifact_revision",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "locator_kind IN ('document', 'table', 'image', 'audio', 'video', "
            "'external_record')",
            name="ck_evidence_spans_locator_kind",
        ),
        sa.CheckConstraint(
            "coordinate_space IS NULL OR coordinate_space IN ('normalized', 'pixel')",
            name="ck_evidence_spans_coordinate_space",
        ),
        sa.CheckConstraint(
            "bbox IS NULL OR coordinate_space IS NOT NULL",
            name="ck_evidence_spans_bbox_space",
        ),
        sa.CheckConstraint("page IS NULL OR page >= 1", name="ck_evidence_spans_page"),
        sa.CheckConstraint(
            "row_number IS NULL OR row_number >= 1", name="ck_evidence_spans_row"
        ),
        sa.CheckConstraint(
            "frame_index IS NULL OR frame_index >= 0",
            name="ck_evidence_spans_frame",
        ),
        sa.CheckConstraint(
            "(start_ms IS NULL AND end_ms IS NULL) OR "
            "(start_ms >= 0 AND end_ms > start_ms)",
            name="ck_evidence_spans_time_range",
        ),
        sa.CheckConstraint(
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
    )
    op.create_index("ix_evidence_spans_tenant_id", "evidence_spans", ["tenant_id"])
    op.create_index("ix_evidence_spans_artifact_id", "evidence_spans", ["artifact_id"])
    op.create_index(
        "ix_evidence_spans_asset_revision_id", "evidence_spans", ["asset_revision_id"]
    )
    op.create_index(
        "ix_evidence_spans_revision_locator",
        "evidence_spans",
        ["asset_revision_id", "locator_kind"],
    )

    op.add_column(
        "documents", sa.Column("source_asset_id", UUID(as_uuid=True), nullable=True)
    )
    op.create_foreign_key(
        "fk_documents_tenant_source_asset",
        "documents",
        "source_assets",
        ["tenant_id", "source_asset_id"],
        ["tenant_id", "id"],
    )
    op.create_index("ix_documents_source_asset_id", "documents", ["source_asset_id"])
    op.create_index(
        "uq_documents_tenant_source_asset",
        "documents",
        ["tenant_id", "source_asset_id"],
        unique=True,
        postgresql_where=sa.text("source_asset_id IS NOT NULL"),
    )

    op.add_column(
        "mka_knowledge_capture_sessions",
        sa.Column("source_asset_id", UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "mka_knowledge_capture_sessions",
        sa.Column("source_asset_revision_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_mka_capture_tenant_source_asset",
        "mka_knowledge_capture_sessions",
        "source_assets",
        ["tenant_id", "source_asset_id"],
        ["tenant_id", "id"],
    )
    op.create_foreign_key(
        "fk_mka_capture_tenant_asset_revision",
        "mka_knowledge_capture_sessions",
        "asset_revisions",
        ["tenant_id", "source_asset_id", "source_asset_revision_id"],
        ["tenant_id", "asset_id", "id"],
    )
    op.create_check_constraint(
        "ck_mka_capture_revision_requires_asset",
        "mka_knowledge_capture_sessions",
        "source_asset_revision_id IS NULL OR source_asset_id IS NOT NULL",
    )
    op.create_index(
        "ix_mka_knowledge_capture_sessions_source_asset_id",
        "mka_knowledge_capture_sessions",
        ["source_asset_id"],
    )
    op.create_index(
        "ix_mka_knowledge_capture_sessions_source_asset_revision_id",
        "mka_knowledge_capture_sessions",
        ["source_asset_revision_id"],
    )

    _enable_rls()


def downgrade() -> None:
    op.drop_index(
        "ix_mka_knowledge_capture_sessions_source_asset_revision_id",
        table_name="mka_knowledge_capture_sessions",
    )
    op.drop_index(
        "ix_mka_knowledge_capture_sessions_source_asset_id",
        table_name="mka_knowledge_capture_sessions",
    )
    op.drop_constraint(
        "ck_mka_capture_revision_requires_asset",
        "mka_knowledge_capture_sessions",
        type_="check",
    )
    op.drop_constraint(
        "fk_mka_capture_tenant_asset_revision",
        "mka_knowledge_capture_sessions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_mka_capture_tenant_source_asset",
        "mka_knowledge_capture_sessions",
        type_="foreignkey",
    )
    op.drop_column("mka_knowledge_capture_sessions", "source_asset_revision_id")
    op.drop_column("mka_knowledge_capture_sessions", "source_asset_id")

    op.drop_index("uq_documents_tenant_source_asset", table_name="documents")
    op.drop_index("ix_documents_source_asset_id", table_name="documents")
    op.drop_constraint(
        "fk_documents_tenant_source_asset", "documents", type_="foreignkey"
    )
    op.drop_column("documents", "source_asset_id")

    for table in reversed(_TENANT_TABLES):
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
    op.drop_table("evidence_spans")
    op.drop_table("derived_artifacts")
    op.drop_table("asset_revisions")
    op.drop_table("source_assets")
