"""Add immutable artifact review decisions for video publication.

Revision ID: video_artifact_review_f1_009
Revises: ingestion_job_c1_008
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "video_artifact_review_f1_009"
down_revision: str | None = "ingestion_job_c1_008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "artifact_review_decisions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column("artifact_id", UUID(as_uuid=True), nullable=False),
        sa.Column("asset_revision_id", UUID(as_uuid=True), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "reviewer_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "tenant_id", "artifact_id", name="uq_artifact_review_decision"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "artifact_id", "asset_revision_id"],
            [
                "derived_artifacts.tenant_id",
                "derived_artifacts.id",
                "derived_artifacts.asset_revision_id",
            ],
            name="fk_artifact_review_decision_artifact_revision",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "decision IN ('approved', 'rejected')",
            name="ck_artifact_review_decision_value",
        ),
    )
    op.create_index(
        "ix_artifact_review_decisions_tenant_id",
        "artifact_review_decisions",
        ["tenant_id"],
    )
    op.create_index(
        "ix_artifact_review_decisions_artifact_id",
        "artifact_review_decisions",
        ["artifact_id"],
    )
    op.create_index(
        "ix_artifact_review_decisions_asset_revision_id",
        "artifact_review_decisions",
        ["asset_revision_id"],
    )
    op.create_index(
        "ix_artifact_review_decisions_reviewer_id",
        "artifact_review_decisions",
        ["reviewer_id"],
    )
    op.create_index(
        "ix_artifact_review_tenant_revision_created",
        "artifact_review_decisions",
        ["tenant_id", "asset_revision_id", "created_at"],
    )
    op.execute('ALTER TABLE "artifact_review_decisions" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "artifact_review_decisions" FORCE ROW LEVEL SECURITY')
    op.execute(
        """
        CREATE POLICY tenant_isolation ON "artifact_review_decisions"
          USING (
            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
            OR current_setting('app.bypass_rls', true) = 'on'
          )
          WITH CHECK (
            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
            OR current_setting('app.bypass_rls', true) = 'on'
          )
        """
    )


def downgrade() -> None:
    op.execute('DROP POLICY IF EXISTS tenant_isolation ON "artifact_review_decisions"')
    op.drop_table("artifact_review_decisions")
