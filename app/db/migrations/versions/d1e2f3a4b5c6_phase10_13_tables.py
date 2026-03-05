"""Phase 7/10/13 tables: chat_feedbacks, watch_folders, review_items, document_versions, categories, kb_backups, knowledge_gaps, integrity_reports

Revision ID: d1e2f3a4b5c6
Revises: c7c9c43b1a3d
Create Date: 2025-01-01 00:00:00.000000

"""
from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers
revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, None] = "c7c9c43b1a3d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Phase 7-5: Chat Feedbacks ──
    op.create_table(
        "chat_feedbacks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, index=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("message_id", UUID(as_uuid=True), sa.ForeignKey("messages.id"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("rating", sa.SmallInteger, nullable=False),
        sa.Column("category", sa.String(50), nullable=True),
        sa.Column("comment", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "message_id", name="uq_feedback_user_message"),
    )

    # ── Phase 10: Watch Folders ──
    op.create_table(
        "watch_folders",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("folder_path", sa.Text, nullable=False),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("recursive", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("max_depth", sa.Integer, nullable=False, server_default="10"),
        sa.Column("allowed_extensions", sa.Text, nullable=True),
        sa.Column("default_category", sa.String(255), nullable=True),
        sa.Column("last_scan_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_files_watched", sa.Integer, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── Phase 10: Review Items ──
    op.create_table(
        "review_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),

        # File info
        sa.Column("file_path", sa.Text, nullable=False),
        sa.Column("file_name", sa.String(512), nullable=False),
        sa.Column("file_size", sa.Integer, nullable=True),
        sa.Column("file_ext", sa.String(20), nullable=True),
        sa.Column("watch_folder_id", UUID(as_uuid=True), sa.ForeignKey("watch_folders.id"), nullable=True),

        # AI classification
        sa.Column("suggested_category", sa.String(255), nullable=True),
        sa.Column("suggested_subcategory", sa.String(255), nullable=True),
        sa.Column("suggested_tags", JSONB, nullable=True),
        sa.Column("confidence_score", sa.Float, nullable=True),
        sa.Column("reasoning", sa.Text, nullable=True),

        # Review
        sa.Column("status", sa.String(50), nullable=False, server_default="pending", index=True),
        sa.Column("approved_category", sa.String(255), nullable=True),
        sa.Column("approved_tags", JSONB, nullable=True),
        sa.Column("reviewer_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("review_note", sa.Text, nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),

        # Indexing result
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("documents.id"), nullable=True),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("indexing_error", sa.Text, nullable=True),

        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, index=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── Phase 13-1: Document Versions ──
    op.create_table(
        "documentversions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, index=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("documents.id"), nullable=False, index=True),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("filename", sa.String, nullable=False),
        sa.Column("file_path", sa.String, nullable=True),
        sa.Column("file_size", sa.Integer, nullable=True),
        sa.Column("file_type", sa.String, nullable=True),
        sa.Column("chunk_count", sa.Integer, nullable=True),
        sa.Column("status", sa.String, nullable=False, server_default="completed"),
        sa.Column("quality_report", sa.JSON, nullable=True),
        sa.Column("uploaded_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("change_note", sa.Text, nullable=True),
        sa.Column("content_snapshot", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── Phase 13-5: Categories ──
    op.create_table(
        "categories",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, index=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("parent_id", UUID(as_uuid=True), sa.ForeignKey("categories.id"), nullable=True, index=True),
        sa.Column("sort_order", sa.Integer, server_default="0"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("document_count", sa.Integer, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── Phase 13-5: Category Revisions ──
    op.create_table(
        "categoryrevisions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, index=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("category_id", UUID(as_uuid=True), sa.ForeignKey("categories.id"), nullable=True, index=True),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("action", sa.String, nullable=False),
        sa.Column("before_json", sa.JSON, nullable=True),
        sa.Column("after_json", sa.JSON, nullable=True),
        sa.Column("actor_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── Phase 13-7: KB Backups ──
    op.create_table(
        "kbbackups",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, index=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=True, index=True),
        sa.Column("backup_type", sa.String, nullable=False, server_default="full"),
        sa.Column("status", sa.String, nullable=False, server_default="running"),
        sa.Column("file_path", sa.String, nullable=True),
        sa.Column("file_size_bytes", sa.Integer, nullable=True),
        sa.Column("document_count", sa.Integer, nullable=True),
        sa.Column("chunk_count", sa.Integer, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("initiated_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
    )

    # ── Phase 13-4: Knowledge Gaps ──
    op.create_table(
        "knowledgegaps",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, index=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("query_text", sa.Text, nullable=False),
        sa.Column("confidence_score", sa.Float, nullable=False),
        sa.Column("suggested_topic", sa.String, nullable=True),
        sa.Column("category_name", sa.String, nullable=True),
        sa.Column("conversation_id", UUID(as_uuid=True), sa.ForeignKey("conversations.id"), nullable=True),
        sa.Column("message_id", UUID(as_uuid=True), sa.ForeignKey("messages.id"), nullable=True),
        sa.Column("status", sa.String, server_default="open"),
        sa.Column("resolved_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("resolved_document_id", UUID(as_uuid=True), sa.ForeignKey("documents.id"), nullable=True),
        sa.Column("resolve_note", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── Phase 13-6: Integrity Reports ──
    op.create_table(
        "integrityreports",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, index=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=True, index=True),
        sa.Column("status", sa.String, nullable=False, server_default="running"),
        sa.Column("total_documents", sa.Integer, server_default="0"),
        sa.Column("total_chunks", sa.Integer, server_default="0"),
        sa.Column("orphan_chunks", sa.Integer, server_default="0"),
        sa.Column("missing_embeddings", sa.Integer, server_default="0"),
        sa.Column("failed_documents", sa.Integer, server_default="0"),
        sa.Column("stale_documents", sa.Integer, server_default="0"),
        sa.Column("detail_json", sa.JSON, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("integrityreports")
    op.drop_table("knowledgegaps")
    op.drop_table("kbbackups")
    op.drop_table("categoryrevisions")
    op.drop_table("categories")
    op.drop_table("documentversions")
    op.drop_table("review_items")
    op.drop_table("watch_folders")
    op.drop_table("chat_feedbacks")
