"""Add KQ4 typed knowledge kinds, relation provenance and section paths.

Revision ID: knowledge_typed_relation_kq4_001
Revises: input_i8_pilot_evidence_001
"""

from __future__ import annotations

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "knowledge_typed_relation_kq4_001"
down_revision: str | None = "input_i8_pilot_evidence_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UNIT_TYPES = (
    "narrative",
    "fact",
    "definition",
    "condition",
    "exception",
    "timing",
    "formula",
    "list_member",
    "workflow_step",
    "table_fact",
    "record_field",
    "role_assignment",
    "contact",
    "row",
    "field",
    "procedure",
    "knowhow",
    "entity",
    "compiled",
)


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.add_column(
        "evidence_spans",
        sa.Column(
            "section_path",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )
    op.drop_constraint("ck_knowledge_units_type", "knowledge_units", type_="check")
    op.create_check_constraint(
        "ck_knowledge_units_type",
        "knowledge_units",
        f"unit_type IN ({_quoted(_UNIT_TYPES)})",
    )
    op.create_table(
        "knowledge_unit_relation_projections",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False
        ),
        sa.Column("relation_key", sa.String(length=700), nullable=False),
        sa.Column("source_revision_id", UUID(as_uuid=True), nullable=False),
        sa.Column("target_revision_id", UUID(as_uuid=True), nullable=False),
        sa.Column("relation_kind", sa.String(length=32), nullable=False),
        sa.Column("source_content_hash", sa.String(length=71), nullable=False),
        sa.Column("target_content_hash", sa.String(length=71), nullable=False),
        sa.Column("projector_version", sa.String(length=100), nullable=False),
        sa.Column(
            "provenance_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column(
            "schema_version", sa.String(length=20), nullable=False, server_default="1.0"
        ),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "relation_key",
            name="uq_knowledge_unit_relation_projections_key",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "source_revision_id"],
            ["knowledge_unit_revisions.tenant_id", "knowledge_unit_revisions.id"],
            name="fk_knowledge_unit_relation_projections_source_revision",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "target_revision_id"],
            ["knowledge_unit_revisions.tenant_id", "knowledge_unit_revisions.id"],
            name="fk_knowledge_unit_relation_projections_target_revision",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "relation_kind IN ('condition','exception','member','next_step','same_record')",
            name="ck_knowledge_unit_relation_projections_kind",
        ),
        sa.CheckConstraint(
            "source_revision_id <> target_revision_id",
            name="ck_knowledge_unit_relation_projections_distinct",
        ),
    )
    for column in (
        "tenant_id",
        "source_revision_id",
        "target_revision_id",
        "relation_kind",
        "created_by",
    ):
        op.create_index(
            f"ix_knowledge_unit_relation_projections_{column}",
            "knowledge_unit_relation_projections",
            [column],
        )
    op.create_index(
        "ix_knowledge_unit_relation_projections_source_kind",
        "knowledge_unit_relation_projections",
        ["source_revision_id", "relation_kind"],
    )
    op.execute(
        'ALTER TABLE "knowledge_unit_relation_projections" ENABLE ROW LEVEL SECURITY'
    )
    op.execute(
        '''CREATE POLICY tenant_isolation ON "knowledge_unit_relation_projections"
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
          OR current_setting('app.bypass_rls', true) = 'on')
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
          OR current_setting('app.bypass_rls', true) = 'on')'''
    )
    if os.environ.get("RLS_ENFORCEMENT_ENABLED", "false").lower() == "true":
        op.execute(
            'ALTER TABLE "knowledge_unit_relation_projections" FORCE ROW LEVEL SECURITY'
        )


def downgrade() -> None:
    op.drop_table("knowledge_unit_relation_projections")
    op.drop_constraint("ck_knowledge_units_type", "knowledge_units", type_="check")
    op.create_check_constraint(
        "ck_knowledge_units_type",
        "knowledge_units",
        "unit_type IN ('narrative','row','field','procedure','knowhow','entity','compiled')",
    )
    op.drop_column("evidence_spans", "section_path")
