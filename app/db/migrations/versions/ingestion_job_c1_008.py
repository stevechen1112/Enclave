"""Add common capability-routed ingestion lifecycle.

Revision ID: ingestion_job_c1_008
Revises: asset_identity_b1_007
"""

from __future__ import annotations

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "ingestion_job_c1_008"
down_revision: str | None = "asset_identity_b1_007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("ingestion_jobs", "ingestion_job_events")
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


def upgrade() -> None:
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False
        ),
        sa.Column("asset_revision_id", UUID(as_uuid=True), nullable=False),
        sa.Column("adapter_key", sa.String(length=150), nullable=False),
        sa.Column("adapter_version", sa.String(length=100), nullable=False),
        sa.Column(
            "requested_capabilities", sa.JSON(), nullable=False, server_default="[]"
        ),
        sa.Column("idempotency_key", sa.String(length=500), nullable=False),
        sa.Column(
            "status", sa.String(length=32), nullable=False, server_default="queued"
        ),
        sa.Column(
            "phase", sa.String(length=100), nullable=False, server_default="queued"
        ),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "quality_state",
            sa.String(length=32),
            nullable=False,
            server_default="provisional",
        ),
        sa.Column("readiness", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("error", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("correlation_id", sa.String(length=255), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "id", name="uq_ingestion_jobs_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_ingestion_jobs_idempotency"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "asset_revision_id"],
            ["asset_revisions.tenant_id", "asset_revisions.id"],
            name="fk_ingestion_jobs_tenant_revision",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'review_required', 'ready', 'failed', 'cancelled')",
            name="ck_ingestion_jobs_status",
        ),
        sa.CheckConstraint("attempt >= 0", name="ck_ingestion_jobs_attempt"),
        sa.CheckConstraint(
            "quality_state IN ('provisional', 'review_required', 'ready', 'rejected')",
            name="ck_ingestion_jobs_quality_state",
        ),
    )
    op.create_index("ix_ingestion_jobs_tenant_id", "ingestion_jobs", ["tenant_id"])
    op.create_index(
        "ix_ingestion_jobs_asset_revision_id", "ingestion_jobs", ["asset_revision_id"]
    )
    op.create_index("ix_ingestion_jobs_status", "ingestion_jobs", ["status"])
    op.create_index(
        "ix_ingestion_jobs_correlation_id", "ingestion_jobs", ["correlation_id"]
    )
    op.create_index(
        "ix_ingestion_jobs_tenant_status_created",
        "ingestion_jobs",
        ["tenant_id", "status", "created_at"],
    )

    op.create_table(
        "ingestion_job_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False
        ),
        sa.Column("job_id", UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("from_status", sa.String(length=32), nullable=True),
        sa.Column("to_status", sa.String(length=32), nullable=False),
        sa.Column("phase", sa.String(length=100), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "job_id"],
            ["ingestion_jobs.tenant_id", "ingestion_jobs.id"],
            name="fk_ingestion_job_events_tenant_job",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "tenant_id", "job_id", "sequence", name="uq_ingestion_job_events_sequence"
        ),
        sa.CheckConstraint("sequence >= 1", name="ck_ingestion_job_events_sequence"),
    )
    op.create_index(
        "ix_ingestion_job_events_tenant_id", "ingestion_job_events", ["tenant_id"]
    )
    op.create_index(
        "ix_ingestion_job_events_job_id", "ingestion_job_events", ["job_id"]
    )
    op.create_index(
        "ix_ingestion_job_events_job_created",
        "ingestion_job_events",
        ["job_id", "created_at"],
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
    op.drop_table("ingestion_job_events")
    op.drop_table("ingestion_jobs")
