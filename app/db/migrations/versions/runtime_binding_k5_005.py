"""Persist frontend and deployment bindings on runtime releases.

Revision ID: runtime_binding_k5_005
Revises: demo_master_role_k4_004
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "runtime_binding_k5_005"
down_revision: str | None = "demo_master_role_k4_004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_runtime_releases",
        sa.Column("frontend_image_digest", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "knowledge_runtime_releases",
        sa.Column("deployment_manifest_id", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("knowledge_runtime_releases", "deployment_manifest_id")
    op.drop_column("knowledge_runtime_releases", "frontend_image_digest")
