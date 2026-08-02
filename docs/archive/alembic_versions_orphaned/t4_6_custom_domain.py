"""Add custom_domain table (T4-6)

⚠️ DEPRECATED — Superseded by c7c9c43b1a3d_add_custom_domains.py in the primary chain.
Do not apply this migration.

Revision ID: t4_6_custom_domain
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "t4_6_custom_domain"
down_revision = "t4_3_branding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customdomain",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False, index=True),
        sa.Column("domain", sa.String(255), unique=True, nullable=False, index=True),
        sa.Column("verification_token", sa.String(64), nullable=False),
        sa.Column("verified", sa.Boolean(), default=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ssl_provisioned", sa.Boolean(), default=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("customdomain")
