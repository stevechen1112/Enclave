"""
⚠️ DEPRECATED — This migration is in the secondary (disconnected) alembic chain.
Most indexes are already created in the primary chain's initial schema (450ae450e023).

T4-15 資料庫調優 — 索引最佳化 Migration
=========================================

針對高頻查詢路徑新增缺失索引和複合索引。
基於 CRUD 層常用查詢模式分析。
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "t4_15_db_indexes"
down_revision = "t4_6_custom_domain"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -----------------------------------------------------------------------
    # 1. users — tenant_id 缺少索引（所有 tenant-scoped user 查詢的關鍵欄位）
    # -----------------------------------------------------------------------
    op.create_index(
        "ix_users_tenant_id",
        "users",
        ["tenant_id"],
    )

    # -----------------------------------------------------------------------
    # 2. audit_logs — created_at 單欄索引 + 複合索引（時間範圍查詢）
    # -----------------------------------------------------------------------
    op.create_index(
        "ix_audit_logs_created_at",
        "auditlogs",
        ["created_at"],
    )
    op.create_index(
        "ix_audit_logs_tenant_created",
        "auditlogs",
        ["tenant_id", "created_at"],
    )

    # -----------------------------------------------------------------------
    # 3. usage_records — created_at + 複合索引（月度聚合查詢）
    # -----------------------------------------------------------------------
    op.create_index(
        "ix_usage_records_created_at",
        "usagerecords",
        ["created_at"],
    )
    op.create_index(
        "ix_usage_records_tenant_created",
        "usagerecords",
        ["tenant_id", "created_at"],
    )
    op.create_index(
        "ix_usage_records_tenant_action_created",
        "usagerecords",
        ["tenant_id", "action_type", "created_at"],
    )

    # -----------------------------------------------------------------------
    # 4. documents — status 欄位索引 + 複合索引
    # -----------------------------------------------------------------------
    op.create_index(
        "ix_documents_status",
        "documents",
        ["status"],
    )
    op.create_index(
        "ix_documents_tenant_status",
        "documents",
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_documents_uploaded_by",
        "documents",
        ["uploaded_by"],
    )

    # -----------------------------------------------------------------------
    # 5. document_chunks — 複合索引（按 document_id + chunk_index 排序）
    # -----------------------------------------------------------------------
    op.create_index(
        "ix_document_chunks_doc_index",
        "documentchunks",
        ["document_id", "chunk_index"],
    )

    # -----------------------------------------------------------------------
    # 6. conversations — 複合索引（user 的對話列表查詢）
    # -----------------------------------------------------------------------
    op.create_index(
        "ix_conversations_tenant_user",
        "conversations",
        ["tenant_id", "user_id"],
    )

    # -----------------------------------------------------------------------
    # 7. messages — created_at（逆序取最新訊息）
    # -----------------------------------------------------------------------
    op.create_index(
        "ix_messages_created_at",
        "messages",
        ["created_at"],
    )
    op.create_index(
        "ix_messages_conversation_created",
        "messages",
        ["conversation_id", "created_at"],
    )

    # -----------------------------------------------------------------------
    # 8. retrieval_traces — 缺少的 FK 索引
    # -----------------------------------------------------------------------
    op.create_index(
        "ix_retrieval_traces_tenant_id",
        "retrievaltraces",
        ["tenant_id"],
    )
    op.create_index(
        "ix_retrieval_traces_conversation_id",
        "retrievaltraces",
        ["conversation_id"],
    )

    # -----------------------------------------------------------------------
    # 9. tenants — plan + status 索引（Admin 查詢 filter）
    # -----------------------------------------------------------------------
    op.create_index(
        "ix_tenants_plan",
        "tenants",
        ["plan"],
    )
    op.create_index(
        "ix_tenants_status",
        "tenants",
        ["status"],
    )

    # -----------------------------------------------------------------------
    # 10. departments — parent_id + 複合索引
    # -----------------------------------------------------------------------
    op.create_index(
        "ix_departments_parent_id",
        "departments",
        ["parent_id"],
    )
    op.create_index(
        "ix_departments_tenant_active",
        "departments",
        ["tenant_id", "is_active"],
    )

    # -----------------------------------------------------------------------
    # 11. feature_permissions — 複合索引（Tenant+Feature+Role 三欄 lookup）
    # -----------------------------------------------------------------------
    op.create_index(
        "ix_feature_permissions_tenant_feature_role",
        "featurepermissions",
        ["tenant_id", "feature", "role"],
    )


def downgrade() -> None:
    # 按建立順序反向刪除
    op.drop_index("ix_feature_permissions_tenant_feature_role", table_name="featurepermissions")
    op.drop_index("ix_departments_tenant_active", table_name="departments")
    op.drop_index("ix_departments_parent_id", table_name="departments")
    op.drop_index("ix_tenants_status", table_name="tenants")
    op.drop_index("ix_tenants_plan", table_name="tenants")
    op.drop_index("ix_retrieval_traces_conversation_id", table_name="retrievaltraces")
    op.drop_index("ix_retrieval_traces_tenant_id", table_name="retrievaltraces")
    op.drop_index("ix_messages_conversation_created", table_name="messages")
    op.drop_index("ix_messages_created_at", table_name="messages")
    op.drop_index("ix_conversations_tenant_user", table_name="conversations")
    op.drop_index("ix_document_chunks_doc_index", table_name="documentchunks")
    op.drop_index("ix_documents_uploaded_by", table_name="documents")
    op.drop_index("ix_documents_tenant_status", table_name="documents")
    op.drop_index("ix_documents_status", table_name="documents")
    op.drop_index("ix_usage_records_tenant_action_created", table_name="usagerecords")
    op.drop_index("ix_usage_records_tenant_created", table_name="usagerecords")
    op.drop_index("ix_usage_records_created_at", table_name="usagerecords")
    op.drop_index("ix_audit_logs_tenant_created", table_name="auditlogs")
    op.drop_index("ix_audit_logs_created_at", table_name="auditlogs")
    op.drop_index("ix_users_tenant_id", table_name="users")
