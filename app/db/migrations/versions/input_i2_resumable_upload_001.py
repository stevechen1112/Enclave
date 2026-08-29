"""Platform-wide tenant-scoped resumable upload sessions.

Revision ID: input_i2_resumable_upload_001
Revises: p5_cost_guardrails_001
"""
import os

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "input_i2_resumable_upload_001"
down_revision = "p5_cost_guardrails_001"
branch_labels = None
depends_on = None


def _rls(table: str) -> None:
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
        "upload_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("owner_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(500), nullable=False),
        sa.Column("filename", sa.String(500), nullable=False),
        sa.Column("media_type", sa.String(255), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("part_size", sa.Integer(), nullable=False),
        sa.Column("total_parts", sa.Integer(), nullable=False),
        sa.Column("received_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("received_parts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(32), nullable=False, server_default="initialized"),
        sa.Column("title", sa.String(500)),
        sa.Column("department_id", UUID(as_uuid=True), sa.ForeignKey("departments.id")),
        sa.Column("data_classification", sa.String(50), nullable=False, server_default="internal"),
        sa.Column("context_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("expected_sha256", sa.String(64)),
        sa.Column("content_sha256", sa.String(64)),
        sa.Column("staging_key", sa.String(128), nullable=False),
        sa.Column("provider_upload_id", sa.String(1000), nullable=False),
        sa.Column("staging_completed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("asset_id", UUID(as_uuid=True)),
        sa.Column("error_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True)),
        sa.Column("aborted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("tenant_id", "id", name="uq_upload_sessions_tenant_id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_upload_sessions_idempotency"),
        sa.ForeignKeyConstraint(["tenant_id", "asset_id"], ["source_assets.tenant_id", "source_assets.id"], name="fk_upload_sessions_tenant_asset"),
        sa.CheckConstraint("byte_size > 0", name="ck_upload_sessions_byte_size"),
        sa.CheckConstraint("part_size > 0", name="ck_upload_sessions_part_size"),
        sa.CheckConstraint("total_parts > 0", name="ck_upload_sessions_total_parts"),
        sa.CheckConstraint("received_bytes >= 0", name="ck_upload_sessions_received_bytes"),
        sa.CheckConstraint("received_parts >= 0", name="ck_upload_sessions_received_parts"),
        sa.CheckConstraint("status IN ('initialized','uploading','committing','committed','aborted','expired','failed')", name="ck_upload_sessions_status"),
    )
    op.create_index("ix_upload_sessions_tenant_id", "upload_sessions", ["tenant_id"])
    op.create_index("ix_upload_sessions_owner_id", "upload_sessions", ["owner_id"])
    op.create_index("ix_upload_sessions_status", "upload_sessions", ["status"])
    op.create_index("ix_upload_sessions_tenant_owner_status", "upload_sessions", ["tenant_id", "owner_id", "status"])
    op.create_index("ix_upload_sessions_status_expires", "upload_sessions", ["status", "expires_at"])
    op.create_table(
        "upload_parts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("session_id", UUID(as_uuid=True), nullable=False),
        sa.Column("part_number", sa.Integer(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("provider_etag", sa.String(1000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "id", name="uq_upload_parts_tenant_id"),
        sa.UniqueConstraint("tenant_id", "session_id", "part_number", name="uq_upload_parts_session_number"),
        sa.ForeignKeyConstraint(["tenant_id", "session_id"], ["upload_sessions.tenant_id", "upload_sessions.id"], name="fk_upload_parts_tenant_session", ondelete="CASCADE"),
        sa.CheckConstraint("part_number >= 1", name="ck_upload_parts_number"),
        sa.CheckConstraint("byte_size > 0", name="ck_upload_parts_size"),
        sa.CheckConstraint("length(sha256) = 64", name="ck_upload_parts_sha256"),
    )
    op.create_index("ix_upload_parts_tenant_id", "upload_parts", ["tenant_id"])
    op.create_index("ix_upload_parts_session_id", "upload_parts", ["session_id"])
    _rls("upload_sessions")
    _rls("upload_parts")


def downgrade() -> None:
    op.drop_table("upload_parts")
    op.drop_table("upload_sessions")
