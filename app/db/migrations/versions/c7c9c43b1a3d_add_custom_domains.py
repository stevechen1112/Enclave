"""add_custom_domains

Revision ID: c7c9c43b1a3d
Revises: a1b2c3d4e5f6
Create Date: 2026-02-12

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c7c9c43b1a3d"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "customdomains",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("verification_token", sa.String(length=64), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ssl_provisioned", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("domain", name="uq_customdomains_domain"),
    )

    op.create_index(op.f("ix_customdomains_id"), "customdomains", ["id"], unique=False)
    op.create_index(op.f("ix_customdomains_tenant_id"), "customdomains", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_customdomains_domain"), "customdomains", ["domain"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_customdomains_domain"), table_name="customdomains")
    op.drop_index(op.f("ix_customdomains_tenant_id"), table_name="customdomains")
    op.drop_index(op.f("ix_customdomains_id"), table_name="customdomains")
    op.drop_table("customdomains")
