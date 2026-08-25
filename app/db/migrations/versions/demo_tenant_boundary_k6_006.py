"""Mark the only tenant eligible for passwordless demo sessions.

Revision ID: demo_tenant_boundary_k6_006
Revises: runtime_binding_k5_005
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "demo_tenant_boundary_k6_006"
down_revision: str | None = "runtime_binding_k5_005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "is_demo",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index("ix_tenants_is_demo", "tenants", ["is_demo"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_tenants_is_demo", table_name="tenants")
    op.drop_column("tenants", "is_demo")
