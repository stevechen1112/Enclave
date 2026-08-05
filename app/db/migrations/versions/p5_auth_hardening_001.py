"""CG-AUTH-SSO：users 加 email_verified／MFA 欄位；重建 tenant_sso_configs。

Revision ID: p5_auth_hardening_001
Revises: p4_sidecar_binding_trigger_001

設計要點：
- email_verified 預設 false，但**既有用戶回填 true**——他們是 Sales-Led
  人工開戶建立，已等同驗證；新用戶（邀請／自助）才走驗證流程。
- tenant_sso_configs 曾於 f7859742ce5d 建立、bf9bb1b20762 同步時被 drop；
  本次以 CG-AUTH-SSO 正式設計重建（auto_create_user 預設 false＝fail-closed）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "p5_auth_hardening_001"
down_revision: Union[str, None] = "p4_sidecar_binding_trigger_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "users",
        sa.Column("mfa_enabled", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column("users", sa.Column("mfa_secret", sa.String(), nullable=True))

    # 既有用戶為人工開戶，視同已驗證；新用戶預設未驗證
    op.execute("UPDATE users SET email_verified = true")

    op.create_table(
        "tenant_sso_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("client_secret", sa.String(), nullable=False),
        sa.Column("redirect_uri", sa.String(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("allowed_domains", sa.JSON(), nullable=True),
        sa.Column("auto_create_user", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("default_role", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_tenant_sso_configs_id", "tenant_sso_configs", ["id"])
    op.create_index("ix_tenant_sso_configs_tenant_id", "tenant_sso_configs", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_tenant_sso_configs_tenant_id", table_name="tenant_sso_configs")
    op.drop_index("ix_tenant_sso_configs_id", table_name="tenant_sso_configs")
    op.drop_table("tenant_sso_configs")
    op.drop_column("users", "mfa_secret")
    op.drop_column("users", "mfa_enabled")
    op.drop_column("users", "email_verified")
