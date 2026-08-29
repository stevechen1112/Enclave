"""Add Input I7 journey timing evidence.

Revision ID: input_i7_operations_metrics_001
Revises: input_i6_connector_batch_001
"""

from collections.abc import Sequence
import os

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "input_i7_operations_metrics_001"
down_revision: str | None = "input_i6_connector_batch_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enable_tenant_rls(table: str) -> None:
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(
        f'''CREATE POLICY tenant_isolation ON "{table}"
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
          OR current_setting('app.bypass_rls', true) = 'on')
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
          OR current_setting('app.bypass_rls', true) = 'on')'''
    )
    if os.environ.get("RLS_ENFORCEMENT_ENABLED", "false").lower() == "true":
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')


def upgrade() -> None:
    op.create_table(
        "input_operation_metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("journey", sa.String(length=32), nullable=False),
        sa.Column("phase", sa.String(length=32), nullable=False),
        sa.Column("workload_kind", sa.String(length=32), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("correlation_id", sa.String(length=255), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("duration_ms >= 0", name="ck_input_operation_metrics_duration"),
        sa.CheckConstraint(
            "journey IN ('upload', 'batch', 'document', 'audio', 'video', 'connector')",
            name="ck_input_operation_metrics_journey",
        ),
        sa.CheckConstraint(
            "outcome IN ('success', 'failed', 'rejected', 'pending')",
            name="ck_input_operation_metrics_outcome",
        ),
        sa.CheckConstraint(
            "phase IN ('acknowledgement', 'transfer', 'queue_wait', 'processing', 'review_readiness')",
            name="ck_input_operation_metrics_phase",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_input_operation_metrics_tenant_id", "input_operation_metrics", ["tenant_id"])
    op.create_index("ix_input_operation_metrics_correlation_id", "input_operation_metrics", ["correlation_id"])
    op.create_index(
        "ix_input_operation_metrics_tenant_phase_recorded",
        "input_operation_metrics",
        ["tenant_id", "phase", "recorded_at"],
    )
    _enable_tenant_rls("input_operation_metrics")


def downgrade() -> None:
    op.drop_table("input_operation_metrics")
