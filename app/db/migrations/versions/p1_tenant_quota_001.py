"""Add tenant quota columns + document quality/chunk fields missing from chain.

Revision ID: p1_tenant_quota_001
Revises: p1_dd_m04_unique_indexes_001
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "p1_tenant_quota_001"
down_revision: Union[str, None] = "p1_dd_m04_unique_indexes_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _cols(table: str) -> set[str]:
    bind = op.get_bind()
    return {c["name"] for c in inspect(bind).get_columns(table)}


def upgrade() -> None:
    tcols = _cols("tenants")
    adds = [
        ("max_users", sa.Integer(), None),
        ("max_documents", sa.Integer(), None),
        ("max_storage_mb", sa.Integer(), None),
        ("monthly_query_limit", sa.Integer(), None),
        ("monthly_token_limit", sa.Integer(), None),
        ("quota_alert_threshold", sa.Float(), "0.8"),
        ("quota_alert_email", sa.String(), None),
    ]
    for name, col_type, server_default in adds:
        if name not in tcols:
            kwargs = {"nullable": True}
            if server_default is not None:
                kwargs["server_default"] = server_default
            op.add_column("tenants", sa.Column(name, col_type, **kwargs))

    dcols = _cols("documents")
    if "chunk_count" not in dcols:
        op.add_column("documents", sa.Column("chunk_count", sa.Integer(), nullable=True))
    if "quality_report" not in dcols:
        op.add_column("documents", sa.Column("quality_report", sa.JSON(), nullable=True))


def downgrade() -> None:
    dcols = _cols("documents")
    if "quality_report" in dcols:
        op.drop_column("documents", "quality_report")
    if "chunk_count" in dcols:
        op.drop_column("documents", "chunk_count")
    tcols = _cols("tenants")
    for name in (
        "quota_alert_email",
        "quota_alert_threshold",
        "monthly_token_limit",
        "monthly_query_limit",
        "max_storage_mb",
        "max_documents",
        "max_users",
    ):
        if name in tcols:
            op.drop_column("tenants", name)
