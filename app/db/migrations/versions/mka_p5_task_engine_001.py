"""MKA 任務引擎核心（職能任務平台重構 Phase 2）。

- mka_task_definitions：版本化任務定義（task_key + version 唯一）。
- mka_task_runs：任務執行紀錄，含 idempotency、provenance、統一狀態機。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "mka_p5_task_engine_001"
down_revision: Union[str, None] = "mka_p4_job_runtime_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mka_task_definitions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("task_key", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("version", sa.String(), nullable=False, server_default="1.0"),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("handler_key", sa.String(), nullable=False),
        sa.Column("module_key", sa.String(), nullable=True),
        sa.Column("applicable_job_role_keys", sa.JSON(), nullable=True),
        sa.Column("input_schema", sa.JSON(), nullable=True),
        sa.Column("required_capabilities", sa.JSON(), nullable=True),
        sa.Column("approval_policy_id", UUID(as_uuid=True), nullable=True),
        sa.Column("output_bindings", sa.JSON(), nullable=True),
        sa.Column("risk_level", sa.String(), nullable=False, server_default="low"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "task_key", "version", name="uq_mka_task_def_key_version"),
    )
    op.create_index("ix_mka_task_definitions_task_key", "mka_task_definitions", ["task_key"])
    op.create_index("ix_mka_task_definitions_tenant_id", "mka_task_definitions", ["tenant_id"])
    op.create_index("ix_mka_task_definitions_module_key", "mka_task_definitions", ["module_key"])

    op.create_table(
        "mka_task_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("task_definition_id", UUID(as_uuid=True), sa.ForeignKey("mka_task_definitions.id"), nullable=False),
        sa.Column("task_key", sa.String(), nullable=False),
        sa.Column("task_version", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("job_role_id", UUID(as_uuid=True), nullable=True),
        sa.Column("module_key", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("input_snapshot", sa.JSON(), nullable=True),
        sa.Column("resolved_context", sa.JSON(), nullable=True),
        sa.Column("field_sources", sa.JSON(), nullable=True),
        sa.Column("provenance", sa.JSON(), nullable=True),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.Column("output_refs", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_mka_task_run_idem"),
    )
    op.create_index("ix_mka_task_runs_task_key", "mka_task_runs", ["task_key"])
    op.create_index("ix_mka_task_runs_tenant_id", "mka_task_runs", ["tenant_id"])
    op.create_index("ix_mka_task_runs_user_id", "mka_task_runs", ["user_id"])
    op.create_index("ix_mka_task_runs_status", "mka_task_runs", ["status"])
    op.create_index("ix_mka_task_runs_tenant_status", "mka_task_runs", ["tenant_id", "status"])


def downgrade() -> None:
    op.drop_table("mka_task_runs")
    op.drop_table("mka_task_definitions")
