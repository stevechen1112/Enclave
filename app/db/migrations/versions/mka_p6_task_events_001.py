"""MKA TaskRun 事件流（職能任務平台重構 Phase 7 可觀測性）。"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "mka_p6_task_events_001"
down_revision: str | None = "mka_p5_task_engine_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "mka_task_run_events" in inspector.get_table_names():
        expected = {
            "id",
            "tenant_id",
            "run_id",
            "event_type",
            "actor_id",
            "payload",
            "created_at",
        }
        actual = {column["name"] for column in inspector.get_columns("mka_task_run_events")}
        missing = sorted(expected - actual)
        if missing:
            raise RuntimeError(
                "Cannot adopt pre-existing mka_task_run_events; missing columns: "
                + ", ".join(missing)
            )
        indexes = {index["name"] for index in inspector.get_indexes("mka_task_run_events")}
        required_indexes = (
            ("ix_mka_task_run_events_tenant_id", ["tenant_id"]),
            ("ix_mka_task_run_events_run_id", ["run_id"]),
            ("ix_mka_task_run_events_event_type", ["event_type"]),
            ("ix_mka_task_run_events_tenant_type", ["tenant_id", "event_type"]),
        )
        for name, columns in required_indexes:
            if name not in indexes:
                op.create_index(name, "mka_task_run_events", columns)
        return
    op.create_table(
        "mka_task_run_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("run_id", UUID(as_uuid=True), sa.ForeignKey("mka_task_runs.id"), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("actor_id", UUID(as_uuid=True), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_mka_task_run_events_tenant_id", "mka_task_run_events", ["tenant_id"])
    op.create_index("ix_mka_task_run_events_run_id", "mka_task_run_events", ["run_id"])
    op.create_index("ix_mka_task_run_events_event_type", "mka_task_run_events", ["event_type"])
    op.create_index(
        "ix_mka_task_run_events_tenant_type",
        "mka_task_run_events",
        ["tenant_id", "event_type"],
    )


def downgrade() -> None:
    op.drop_table("mka_task_run_events")
