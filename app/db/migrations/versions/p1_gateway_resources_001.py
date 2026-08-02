"""Phase 1: gateway_resources table

Revision ID: p1_gateway_resources_001
Revises: p0_kb_outbox_001
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "p1_gateway_resources_001"
down_revision: Union[str, None] = "p0_kb_outbox_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "gateway_resources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("enclave_resource_type", sa.String(), nullable=False),
        sa.Column("enclave_resource_id", sa.String(), nullable=False),
        sa.Column("enclave_revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("provider_instance_id", sa.String(), nullable=True),
        sa.Column("provider_resource_type", sa.String(), nullable=True),
        sa.Column("provider_resource_id", sa.String(), nullable=True),
        sa.Column("provider_revision", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("checksum", sa.String(), nullable=True),
        sa.Column("state", sa.String(), server_default="active"),
        sa.Column("tombstoned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.UniqueConstraint(
            "enclave_resource_type",
            "enclave_resource_id",
            "provider",
            "provider_instance_id",
            name="uq_gateway_resource_mapping",
        ),
    )
    op.create_index("ix_gateway_resources_enclave_resource_id", "gateway_resources", ["enclave_resource_id"])
    op.create_index("ix_gateway_resources_provider", "gateway_resources", ["provider", "provider_resource_id"])


def downgrade() -> None:
    op.drop_index("ix_gateway_resources_provider", table_name="gateway_resources")
    op.drop_index("ix_gateway_resources_enclave_resource_id", table_name="gateway_resources")
    op.drop_table("gateway_resources")
