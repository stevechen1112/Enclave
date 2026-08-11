"""MKA audio retention policy + task cost tables with tenant RLS.

對照 ENGINEERING_PLAN §12.1（音訊保留政策）與 §13.4（每任務 COGS）。
取代原先純記憶體的 AudioRetentionManager 正式路徑。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "mka_p1_audio_retention_001"
down_revision: Union[str, None] = "mka_p0_domain_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TENANT_TABLES = (
    "mka_audio_policies",
    "mka_task_costs",
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


def _enable_rls(table: str) -> None:
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
    op.execute(_TENANT_POLICY.format(table=table))
    op.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')


def upgrade() -> None:
    op.create_table(
        "mka_audio_policies",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, unique=True, index=True),
        sa.Column("save_audio", sa.Boolean, server_default=sa.false()),
        sa.Column("save_transcript", sa.Boolean, server_default=sa.true()),
        sa.Column("audio_retention_days", sa.Integer, server_default="90"),
        sa.Column("transcript_retention_days", sa.Integer, server_default="365"),
        sa.Column("encrypt_at_rest", sa.Boolean, server_default=sa.true()),
        sa.Column("audit_downloads", sa.Boolean, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    op.create_table(
        "mka_task_costs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("task_type", sa.String, nullable=False, index=True),
        sa.Column("task_id", sa.String, nullable=True),
        sa.Column("correlation_id", sa.String, nullable=True),
        sa.Column("stt_cost", sa.Float, server_default="0"),
        sa.Column("llm_cost", sa.Float, server_default="0"),
        sa.Column("embedding_cost", sa.Float, server_default="0"),
        sa.Column("rerank_cost", sa.Float, server_default="0"),
        sa.Column("ocr_cost", sa.Float, server_default="0"),
        sa.Column("source_verify_cost", sa.Float, server_default="0"),
        sa.Column("storage_cost", sa.Float, server_default="0"),
        sa.Column("total_cost", sa.Float, server_default="0"),
        sa.Column("details", sa.JSON, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), index=True),
    )
    for table in _TENANT_TABLES:
        _enable_rls(table)


def downgrade() -> None:
    for table in _TENANT_TABLES:
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
        op.drop_table(table)
