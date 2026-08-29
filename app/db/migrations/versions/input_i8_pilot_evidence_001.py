"""Add Input I8 tenant pilot evidence ledger.

Revision ID: input_i8_pilot_evidence_001
Revises: input_i7_operations_metrics_001
"""

from collections.abc import Sequence
import os

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "input_i8_pilot_evidence_001"
down_revision: str | None = "input_i7_operations_metrics_001"
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
        "input_pilots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("evidence_mode", sa.String(length=16), nullable=False),
        sa.Column("dedicated_environment", sa.Boolean(), nullable=False),
        sa.Column("environment_evidence_sha256", sa.String(length=64), nullable=True),
        sa.Column("data_processing_agreement_ref", sa.String(length=1000), nullable=True),
        sa.Column("journeys", sa.JSON(), nullable=False),
        sa.Column("acceptance_config", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("planned_end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retrospective_sha256", sa.String(length=64), nullable=True),
        sa.Column("retrospective_ref", sa.String(length=1000), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("evidence_mode IN ('live','synthetic')", name="ck_input_pilots_evidence_mode"),
        sa.CheckConstraint("status IN ('draft','ready','running','hold','accepted','rejected')", name="ck_input_pilots_status"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_input_pilots_tenant_id"),
    )
    op.create_index("ix_input_pilots_tenant_id", "input_pilots", ["tenant_id"])
    op.create_index("ix_input_pilots_tenant_status", "input_pilots", ["tenant_id", "status"])

    op.create_table(
        "input_pilot_daily_metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pilot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("metric_date", sa.Date(), nullable=False),
        sa.Column("journey_key", sa.String(length=50), nullable=False),
        sa.Column("total_attempts", sa.Integer(), nullable=False),
        sa.Column("successful_attempts", sa.Integer(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("manual_correction_count", sa.Integer(), nullable=False),
        sa.Column("processing_p95_ms", sa.Integer(), nullable=False),
        sa.Column("retrieval_checks", sa.Integer(), nullable=False),
        sa.Column("cited_retrievals", sa.Integer(), nullable=False),
        sa.Column("friction_count", sa.Integer(), nullable=False),
        sa.Column("source_evidence_sha256", sa.String(length=64), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "total_attempts >= 0 AND successful_attempts >= 0 AND successful_attempts <= total_attempts AND retry_count >= 0 AND manual_correction_count >= 0 AND processing_p95_ms >= 0 AND retrieval_checks >= 0 AND cited_retrievals >= 0 AND cited_retrievals <= retrieval_checks AND friction_count >= 0",
            name="ck_input_pilot_daily_metric_values",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "pilot_id"], ["input_pilots.tenant_id", "input_pilots.id"],
            name="fk_input_pilot_metrics_tenant_pilot", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "pilot_id", "metric_date", "journey_key", name="uq_input_pilot_daily_metric"),
    )
    op.create_index("ix_input_pilot_daily_metrics_tenant_id", "input_pilot_daily_metrics", ["tenant_id"])
    op.create_index("ix_input_pilot_daily_metrics_pilot_id", "input_pilot_daily_metrics", ["pilot_id"])
    op.create_index("ix_input_pilot_metrics_pilot_date", "input_pilot_daily_metrics", ["pilot_id", "metric_date"])

    op.create_table(
        "input_pilot_incidents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pilot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("near_miss", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("data_loss", sa.Boolean(), nullable=False),
        sa.Column("unauthorized_access", sa.Boolean(), nullable=False),
        sa.Column("false_completion", sa.Boolean(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("root_cause", sa.Text(), nullable=True),
        sa.Column("corrective_action", sa.Text(), nullable=True),
        sa.Column("retrospective_sha256", sa.String(length=64), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("severity IN ('low','medium','high','critical')", name="ck_input_pilot_incidents_severity"),
        sa.CheckConstraint("status IN ('open','mitigated','resolved')", name="ck_input_pilot_incidents_status"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "pilot_id"], ["input_pilots.tenant_id", "input_pilots.id"],
            name="fk_input_pilot_incidents_tenant_pilot", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_input_pilot_incidents_tenant_id", "input_pilot_incidents", ["tenant_id"])
    op.create_index("ix_input_pilot_incidents_pilot_id", "input_pilot_incidents", ["pilot_id"])
    op.create_index("ix_input_pilot_incidents_pilot_status", "input_pilot_incidents", ["pilot_id", "status"])

    op.create_table(
        "input_pilot_audits",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pilot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("audit_type", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("findings", sa.JSON(), nullable=False),
        sa.Column("evidence_sha256", sa.String(length=64), nullable=False),
        sa.Column("auditor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("audited_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("audit_type IN ('quality','security','permission')", name="ck_input_pilot_audits_type"),
        sa.CheckConstraint("sample_size >= 0", name="ck_input_pilot_audits_sample_size"),
        sa.CheckConstraint("status IN ('pending','pass','fail')", name="ck_input_pilot_audits_status"),
        sa.ForeignKeyConstraint(["auditor_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "pilot_id"], ["input_pilots.tenant_id", "input_pilots.id"],
            name="fk_input_pilot_audits_tenant_pilot", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_input_pilot_audits_tenant_id", "input_pilot_audits", ["tenant_id"])
    op.create_index("ix_input_pilot_audits_pilot_id", "input_pilot_audits", ["pilot_id"])
    op.create_index("ix_input_pilot_audits_pilot_type", "input_pilot_audits", ["pilot_id", "audit_type"])

    op.create_table(
        "input_pilot_acceptances",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pilot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("signer_name", sa.String(length=200), nullable=False),
        sa.Column("signer_role", sa.String(length=200), nullable=False),
        sa.Column("signed_document_sha256", sa.String(length=64), nullable=False),
        sa.Column("signed_document_ref", sa.String(length=1000), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("decision IN ('accepted','rejected')", name="ck_input_pilot_acceptance_decision"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "pilot_id"], ["input_pilots.tenant_id", "input_pilots.id"],
            name="fk_input_pilot_acceptance_tenant_pilot", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "pilot_id", name="uq_input_pilot_acceptance"),
    )
    op.create_index("ix_input_pilot_acceptances_tenant_id", "input_pilot_acceptances", ["tenant_id"])
    op.create_index("ix_input_pilot_acceptances_pilot_id", "input_pilot_acceptances", ["pilot_id"])
    for table in (
        "input_pilots",
        "input_pilot_daily_metrics",
        "input_pilot_incidents",
        "input_pilot_audits",
        "input_pilot_acceptances",
    ):
        _enable_tenant_rls(table)


def downgrade() -> None:
    op.drop_table("input_pilot_acceptances")
    op.drop_table("input_pilot_audits")
    op.drop_table("input_pilot_incidents")
    op.drop_table("input_pilot_daily_metrics")
    op.drop_table("input_pilots")
