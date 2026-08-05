"""Add Document.genre for catalog-granularity retrieval (ADR-008 / F2).

Revision ID: f2_documents_genre_001
Revises: p1_retrieval_trace_providers_001
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "f2_documents_genre_001"
down_revision: Union[str, None] = "p1_retrieval_trace_providers_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _cols(table: str) -> set[str]:
    bind = op.get_bind()
    return {c["name"] for c in inspect(bind).get_columns(table)}


def upgrade() -> None:
    if "genre" not in _cols("documents"):
        op.add_column(
            "documents",
            sa.Column("genre", sa.String(), nullable=True),
        )
        op.create_index("ix_documents_genre", "documents", ["genre"])


def downgrade() -> None:
    if "genre" in _cols("documents"):
        op.drop_index("ix_documents_genre", table_name="documents")
        op.drop_column("documents", "genre")
