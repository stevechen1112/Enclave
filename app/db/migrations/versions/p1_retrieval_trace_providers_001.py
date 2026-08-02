"""Add RetrievalTrace.providers_called for provider audit (A6).

Revision ID: p1_retrieval_trace_providers_001
Revises: p1_tenant_quota_001
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "p1_retrieval_trace_providers_001"
down_revision: Union[str, None] = "p1_tenant_quota_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _cols(table: str) -> set[str]:
    bind = op.get_bind()
    return {c["name"] for c in inspect(bind).get_columns(table)}


def upgrade() -> None:
    if "providers_called" not in _cols("retrievaltraces"):
        op.add_column(
            "retrievaltraces",
            sa.Column("providers_called", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    if "providers_called" in _cols("retrievaltraces"):
        op.drop_column("retrievaltraces", "providers_called")
