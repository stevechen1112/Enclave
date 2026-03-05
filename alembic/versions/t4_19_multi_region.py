"""
⚠️ DEPRECATED — This migration is in the secondary (disconnected) alembic chain.
Region columns are not used in the current on-prem model.

T4-19 多區域部署 — Tenant region 欄位 Migration
=================================================

新增 region 欄位至 tenants 表，支援多區域資料落地。
"""

from alembic import op
import sqlalchemy as sa

revision = "t4_19_multi_region"
down_revision = "t4_15_db_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 新增 region 欄位，預設 'ap'（亞太 / 台灣）
    op.add_column(
        "tenants",
        sa.Column("region", sa.String(10), nullable=False, server_default="ap"),
    )
    op.create_index("ix_tenants_region", "tenants", ["region"])

    # 新增 data_residency_note 欄位（合規用途：資料落地說明）
    op.add_column(
        "tenants",
        sa.Column("data_residency_note", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenants", "data_residency_note")
    op.drop_index("ix_tenants_region", table_name="tenants")
    op.drop_column("tenants", "region")
