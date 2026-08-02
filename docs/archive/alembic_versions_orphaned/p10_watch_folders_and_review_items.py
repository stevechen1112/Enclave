"""Phase 10: add watch_folders and review_items tables

⚠️ DEPRECATED — This migration is in the secondary (disconnected) alembic chain.
The corrected version with tenant_id (instead of org_id) and proper FKs is in:
  app/db/migrations/versions/d1e2f3a4b5c6_phase10_13_tables.py

Revision ID: p10_watch_folders_review_items
Revises: t7_5_feedback
Create Date: 2026-06-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers
revision = "p10_watch_folders_review_items"
down_revision = "t7_5_feedback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ──────────────────────────────────────────
    # watch_folders
    # ──────────────────────────────────────────
    op.create_table(
        "watch_folders",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("folder_path", sa.Text, nullable=False),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("recursive", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("max_depth", sa.Integer, nullable=False, server_default="10"),
        sa.Column("allowed_extensions", sa.Text, nullable=True),
        sa.Column("default_category", sa.String(255), nullable=True),
        sa.Column("last_scan_at", sa.DateTime, nullable=True),
        sa.Column("total_files_watched", sa.Integer, server_default="0"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_watch_folders_org_id", "watch_folders", ["org_id"])

    # ──────────────────────────────────────────
    # review_items
    # ──────────────────────────────────────────
    op.create_table(
        "review_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("file_path", sa.Text, nullable=False),
        sa.Column("file_name", sa.String(512), nullable=False),
        sa.Column("file_size", sa.Integer, nullable=True),
        sa.Column("file_ext", sa.String(20), nullable=True),
        sa.Column(
            "watch_folder_id",
            UUID(as_uuid=True),
            sa.ForeignKey("watch_folders.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # AI proposal
        sa.Column("suggested_category", sa.String(255), nullable=True),
        sa.Column("suggested_subcategory", sa.String(255), nullable=True),
        sa.Column("suggested_tags", JSONB, nullable=True),
        sa.Column("confidence_score", sa.Float, nullable=True),
        sa.Column("reasoning", sa.Text, nullable=True),
        # human review
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("approved_category", sa.String(255), nullable=True),
        sa.Column("approved_tags", JSONB, nullable=True),
        sa.Column(
            "reviewer_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("review_note", sa.Text, nullable=True),
        sa.Column("reviewed_at", sa.DateTime, nullable=True),
        # indexing
        sa.Column(
            "document_id",
            UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("indexed_at", sa.DateTime, nullable=True),
        sa.Column("indexing_error", sa.Text, nullable=True),
        # timestamps
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_review_items_org_id", "review_items", ["org_id"])
    op.create_index("ix_review_items_status", "review_items", ["status"])
    op.create_index("ix_review_items_created_at", "review_items", ["created_at"])


def downgrade() -> None:
    op.drop_table("review_items")
    op.drop_table("watch_folders")
