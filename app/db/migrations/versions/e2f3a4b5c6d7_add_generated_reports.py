"""Phase 11-2: add generated_reports table

Revision ID: e2f3a4b5c6d7
Revises: 389e29b29360
Create Date: 2026-02-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = 'e2f3a4b5c6d7'
down_revision: Union[str, None] = '389e29b29360'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "generatedreports",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False, server_default="未命名報告"),
        sa.Column("template", sa.String(50), nullable=False),
        sa.Column("prompt", sa.Text, nullable=False),
        sa.Column("context_query", sa.Text, nullable=True),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("word_count", sa.Integer, nullable=True),
        sa.Column("sources", sa.JSON, nullable=True),
        sa.Column("document_ids", sa.JSON, nullable=True),
        sa.Column("is_pinned", sa.Boolean, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_generatedreports_tenant_id", "generatedreports", ["tenant_id"])
    op.create_index("ix_generatedreports_created_by", "generatedreports", ["created_by"])
    op.create_index("ix_generatedreports_template", "generatedreports", ["template"])
    op.create_index("ix_generatedreports_is_pinned", "generatedreports", ["is_pinned"])


def downgrade() -> None:
    op.drop_table("generatedreports")
