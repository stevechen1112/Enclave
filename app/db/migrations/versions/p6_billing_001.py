"""CG-PAY：billing_records 表。

Revision ID: p6_billing_001
Revises: p5_auth_hardening_001
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "p6_billing_001"
down_revision: Union[str, None] = "p5_auth_hardening_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "billing_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=True, unique=True),
        sa.Column("amount_twd", sa.Numeric(10, 2), nullable=False),
        sa.Column("currency", sa.String(3), server_default="TWD"),
        sa.Column("status", sa.String(50), server_default="pending"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("plan", sa.String(50), nullable=True),
        sa.Column("invoice_number", sa.String(100), nullable=True, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_billing_records_tenant_id", "billing_records", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_billing_records_tenant_id", table_name="billing_records")
    op.drop_table("billing_records")
