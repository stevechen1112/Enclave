"""Add white-label branding fields to tenant (T4-3)

⚠️ DEPRECATED — This migration is in the secondary (disconnected) alembic chain.
The primary chain at app/db/migrations/versions/ is authoritative.
Branding columns are not used in the current on-prem model.

Revision ID: t4_3_branding
Revises: 
Create Date: 2025-02-08
"""
from alembic import op
import sqlalchemy as sa

revision = "t4_3_branding"
down_revision = None  # Adjust to actual latest revision
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("brand_name", sa.String(100), nullable=True))
    op.add_column("tenants", sa.Column("brand_logo_url", sa.String(500), nullable=True))
    op.add_column("tenants", sa.Column("brand_primary_color", sa.String(7), nullable=True))
    op.add_column("tenants", sa.Column("brand_secondary_color", sa.String(7), nullable=True))
    op.add_column("tenants", sa.Column("brand_favicon_url", sa.String(500), nullable=True))
    op.add_column("tenants", sa.Column("custom_domain", sa.String(255), nullable=True))
    op.create_unique_constraint("uq_tenant_custom_domain", "tenants", ["custom_domain"])


def downgrade() -> None:
    op.drop_constraint("uq_tenant_custom_domain", "tenants", type_="unique")
    op.drop_column("tenants", "custom_domain")
    op.drop_column("tenants", "brand_favicon_url")
    op.drop_column("tenants", "brand_secondary_color")
    op.drop_column("tenants", "brand_primary_color")
    op.drop_column("tenants", "brand_logo_url")
    op.drop_column("tenants", "brand_name")
