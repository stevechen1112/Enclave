"""Add canonical versioned KnowledgeUnit release authority.

Revision ID: knowledge_authority_h1_012
Revises: video_governance_f3_011
"""

from __future__ import annotations

import os
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "knowledge_authority_h1_012"
down_revision: str | None = "video_governance_f3_011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = (
    "knowledge_units",
    "knowledge_unit_revisions",
    "knowledge_unit_releases",
    "knowledge_unit_release_memberships",
)
_POLICY = """
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


def _json_default(value: str) -> sa.TextClause:
    return sa.text(f"'{value}'::json")


def upgrade() -> None:
    op.create_table(
        "knowledge_units",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False
        ),
        sa.Column("unit_key", sa.String(length=500), nullable=False),
        sa.Column("unit_type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("source_asset_id", UUID(as_uuid=True), nullable=True),
        sa.Column("source_resource_type", sa.String(length=100), nullable=False),
        sa.Column("source_resource_id", sa.String(length=500), nullable=False),
        sa.Column("current_revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "status", sa.String(length=24), nullable=False, server_default="active"
        ),
        sa.Column(
            "metadata_json",
            sa.JSON(),
            nullable=False,
            server_default=_json_default("{}"),
        ),
        sa.Column(
            "schema_version", sa.String(length=20), nullable=False, server_default="1.0"
        ),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("tombstoned_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("tenant_id", "id", name="uq_knowledge_units_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id", "unit_key", name="uq_knowledge_units_tenant_key"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "source_asset_id"],
            ["source_assets.tenant_id", "source_assets.id"],
            name="fk_knowledge_units_tenant_asset",
        ),
        sa.CheckConstraint(
            "unit_type IN ('narrative', 'row', 'field', 'procedure', 'knowhow', "
            "'entity', 'compiled')",
            name="ck_knowledge_units_type",
        ),
        sa.CheckConstraint(
            "current_revision >= 0", name="ck_knowledge_units_current_revision"
        ),
        sa.CheckConstraint(
            "status IN ('active', 'tombstoned')", name="ck_knowledge_units_status"
        ),
    )
    op.create_index("ix_knowledge_units_tenant_id", "knowledge_units", ["tenant_id"])
    op.create_index("ix_knowledge_units_unit_type", "knowledge_units", ["unit_type"])
    op.create_index(
        "ix_knowledge_units_source_asset_id", "knowledge_units", ["source_asset_id"]
    )
    op.create_index("ix_knowledge_units_created_by", "knowledge_units", ["created_by"])
    op.create_index(
        "ix_knowledge_units_tenant_type_status",
        "knowledge_units",
        ["tenant_id", "unit_type", "status"],
    )

    op.create_table(
        "knowledge_unit_revisions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False
        ),
        sa.Column("unit_id", UUID(as_uuid=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=71), nullable=False),
        sa.Column(
            "authority_class",
            sa.String(length=50),
            nullable=False,
            server_default="primary_document",
        ),
        sa.Column(
            "quality_state",
            sa.String(length=24),
            nullable=False,
            server_default="ready",
        ),
        sa.Column(
            "risk_level", sa.String(length=24), nullable=False, server_default="normal"
        ),
        sa.Column(
            "acl_snapshot",
            sa.JSON(),
            nullable=False,
            server_default=_json_default("{}"),
        ),
        sa.Column(
            "applicability_json",
            sa.JSON(),
            nullable=False,
            server_default=_json_default("{}"),
        ),
        sa.Column(
            "metadata_json",
            sa.JSON(),
            nullable=False,
            server_default=_json_default("{}"),
        ),
        sa.Column("source_asset_revision_id", UUID(as_uuid=True)),
        sa.Column("source_artifact_id", UUID(as_uuid=True)),
        sa.Column("policy_revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "schema_version", sa.String(length=20), nullable=False, server_default="1.0"
        ),
        sa.Column("effective_from", sa.DateTime(timezone=True)),
        sa.Column("effective_to", sa.DateTime(timezone=True)),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_knowledge_unit_revisions_tenant_id"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "unit_id",
            "revision",
            name="uq_knowledge_unit_revisions_unit_revision",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "unit_id"],
            ["knowledge_units.tenant_id", "knowledge_units.id"],
            name="fk_knowledge_unit_revisions_tenant_unit",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "source_asset_revision_id"],
            ["asset_revisions.tenant_id", "asset_revisions.id"],
            name="fk_knowledge_unit_revisions_tenant_asset_revision",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "source_artifact_id"],
            ["derived_artifacts.tenant_id", "derived_artifacts.id"],
            name="fk_knowledge_unit_revisions_tenant_artifact",
        ),
        sa.CheckConstraint(
            "revision >= 1", name="ck_knowledge_unit_revisions_revision"
        ),
        sa.CheckConstraint(
            "length(content_hash) IN (64, 71)", name="ck_knowledge_unit_revisions_hash"
        ),
        sa.CheckConstraint(
            "quality_state IN ('provisional', 'review_required', 'ready', 'rejected')",
            name="ck_knowledge_unit_revisions_quality",
        ),
        sa.CheckConstraint(
            "risk_level IN ('low', 'normal', 'high', 'critical')",
            name="ck_knowledge_unit_revisions_risk",
        ),
        sa.CheckConstraint(
            "policy_revision >= 1", name="ck_knowledge_unit_revisions_policy"
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_from IS NULL OR effective_to > effective_from",
            name="ck_knowledge_unit_revisions_effective_period",
        ),
    )
    for column in (
        "tenant_id",
        "unit_id",
        "content_hash",
        "source_asset_revision_id",
        "source_artifact_id",
        "created_by",
    ):
        op.create_index(
            f"ix_knowledge_unit_revisions_{column}",
            "knowledge_unit_revisions",
            [column],
        )
    op.create_index(
        "ix_knowledge_unit_revisions_tenant_quality_created",
        "knowledge_unit_revisions",
        ["tenant_id", "quality_state", "created_at"],
    )

    op.create_table(
        "knowledge_unit_releases",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False
        ),
        sa.Column("release_key", sa.String(length=500), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "scope_kind", sa.String(length=32), nullable=False, server_default="tenant"
        ),
        sa.Column("scope_id", UUID(as_uuid=True)),
        sa.Column("scope_revision_id", UUID(as_uuid=True)),
        sa.Column(
            "status", sa.String(length=24), nullable=False, server_default="candidate"
        ),
        sa.Column("policy_revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("manifest_hash", sa.String(length=64)),
        sa.Column(
            "gate_evidence",
            sa.JSON(),
            nullable=False,
            server_default=_json_default("{}"),
        ),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_knowledge_unit_releases_tenant_id"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "release_key",
            "revision",
            name="uq_knowledge_unit_releases_key_revision",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_knowledge_unit_releases_revision"),
        sa.CheckConstraint(
            "scope_kind IN ('tenant', 'knowledge_base')",
            name="ck_knowledge_unit_releases_scope_kind",
        ),
        sa.CheckConstraint(
            "(scope_kind = 'tenant' AND scope_id IS NULL AND scope_revision_id IS NULL) OR "
            "(scope_kind = 'knowledge_base' AND scope_id IS NOT NULL "
            "AND scope_revision_id IS NOT NULL)",
            name="ck_knowledge_unit_releases_scope",
        ),
        sa.CheckConstraint(
            "status IN ('candidate', 'active', 'retired', 'rejected')",
            name="ck_knowledge_unit_releases_status",
        ),
        sa.CheckConstraint(
            "policy_revision >= 1", name="ck_knowledge_unit_releases_policy"
        ),
    )
    for column in (
        "tenant_id",
        "scope_id",
        "scope_revision_id",
        "created_by",
    ):
        op.create_index(
            f"ix_knowledge_unit_releases_{column}",
            "knowledge_unit_releases",
            [column],
        )
    op.create_index(
        "uq_knowledge_unit_releases_active_key",
        "knowledge_unit_releases",
        ["tenant_id", "release_key"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "knowledge_unit_release_memberships",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False
        ),
        sa.Column("release_id", UUID(as_uuid=True), nullable=False),
        sa.Column("unit_revision_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "acl_snapshot",
            sa.JSON(),
            nullable=False,
            server_default=_json_default("{}"),
        ),
        sa.Column("policy_revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "status", sa.String(length=24), nullable=False, server_default="active"
        ),
        sa.Column("added_by", UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column(
            "activated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("retired_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_knowledge_unit_memberships_tenant_id"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "release_id",
            "unit_revision_id",
            name="uq_knowledge_unit_memberships_release_revision",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "release_id"],
            ["knowledge_unit_releases.tenant_id", "knowledge_unit_releases.id"],
            name="fk_knowledge_unit_memberships_tenant_release",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "unit_revision_id"],
            ["knowledge_unit_revisions.tenant_id", "knowledge_unit_revisions.id"],
            name="fk_knowledge_unit_memberships_tenant_revision",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "policy_revision >= 1", name="ck_knowledge_unit_memberships_policy"
        ),
        sa.CheckConstraint(
            "status IN ('active', 'retired')",
            name="ck_knowledge_unit_memberships_status",
        ),
    )
    for column in ("tenant_id", "release_id", "unit_revision_id", "added_by"):
        op.create_index(
            f"ix_knowledge_unit_release_memberships_{column}",
            "knowledge_unit_release_memberships",
            [column],
        )
    op.create_index(
        "ix_knowledge_unit_memberships_release_status",
        "knowledge_unit_release_memberships",
        ["release_id", "status"],
    )

    force = os.environ.get("RLS_ENFORCEMENT_ENABLED", "false").lower() == "true"
    for table in _TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
        op.execute(_POLICY.format(table=table))
        op.execute(
            f'ALTER TABLE "{table}" {"FORCE" if force else "NO FORCE"} ROW LEVEL SECURITY'
        )


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
        op.drop_table(table)
