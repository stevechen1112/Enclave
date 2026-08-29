"""Add Input I6 replayable connector batch manifests.

Revision ID: input_i6_connector_batch_001
Revises: input_i5_media_product_001
"""

from collections.abc import Sequence
import os

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "input_i6_connector_batch_001"
down_revision: str | None = "input_i5_media_product_001"
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
        "import_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connector_instance_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("root_label", sa.String(length=500), nullable=True),
        sa.Column("shared_metadata", sa.JSON(), nullable=False),
        sa.Column("total_items", sa.Integer(), nullable=False),
        sa.Column("succeeded_items", sa.Integer(), nullable=False),
        sa.Column("failed_items", sa.Integer(), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'partial', 'completed', 'failed')",
            name="ck_import_batches_status",
        ),
        sa.ForeignKeyConstraint(["connector_instance_id"], ["connector_instances.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_import_batches_tenant_id"),
    )
    op.create_index("ix_import_batches_tenant_id", "import_batches", ["tenant_id"])
    op.create_index("ix_import_batches_connector_instance_id", "import_batches", ["connector_instance_id"])
    op.create_index("ix_import_batches_tenant_created", "import_batches", ["tenant_id", "created_at"])
    op.create_table(
        "import_batch_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_record_id", sa.String(length=500), nullable=False),
        sa.Column("parent_source_id", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=71), nullable=True),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resource_json", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("attempts >= 0", name="ck_import_batch_items_attempts"),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed', 'skipped')",
            name="ck_import_batch_items_status",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "batch_id"],
            ["import_batches.tenant_id", "import_batches.id"],
            name="fk_import_batch_items_tenant_batch",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "asset_id"],
            ["source_assets.tenant_id", "source_assets.id"],
            name="fk_import_batch_items_tenant_asset",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "asset_id", "revision_id"],
            ["asset_revisions.tenant_id", "asset_revisions.asset_id", "asset_revisions.id"],
            name="fk_import_batch_items_tenant_revision",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_id", "source_record_id", name="uq_import_batch_item_source"),
    )
    op.create_index("ix_import_batch_items_tenant_id", "import_batch_items", ["tenant_id"])
    op.create_index("ix_import_batch_items_batch_id", "import_batch_items", ["batch_id"])
    op.create_index("ix_import_batch_items_tenant_status", "import_batch_items", ["tenant_id", "status"])
    _enable_tenant_rls("import_batches")
    _enable_tenant_rls("import_batch_items")


def downgrade() -> None:
    op.drop_table("import_batch_items")
    op.drop_table("import_batches")
