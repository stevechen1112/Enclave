"""MKA 職能 runtime 契約（職能任務平台重構 Phase 1）。

- job_modules.allowed_job_role_keys：業務職能 allowlist（空 = 不限職能，向後相容）。
- users.active_job_role_id：多職能使用者的 active 職能持久化。
- tenant_module_bindings.config_version：租戶模組設定的版本號（版本化 merge 用）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "mka_p4_job_runtime_001"
down_revision: Union[str, None] = "mka_p3_knowhow_owner_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "job_modules",
        sa.Column("allowed_job_role_keys", sa.JSON(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "active_job_role_id",
            UUID(as_uuid=True),
            sa.ForeignKey("mka_job_roles.id"),
            nullable=True,
        ),
    )
    op.add_column(
        "tenant_module_bindings",
        sa.Column("config_version", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("tenant_module_bindings", "config_version")
    op.drop_column("users", "active_job_role_id")
    op.drop_column("job_modules", "allowed_job_role_keys")
