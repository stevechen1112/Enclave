"""Phase 0: KB domain model + outbox infrastructure

Revision ID: p0_kb_outbox_001
Revises: e2f3a4b5c6d7
Create Date: 2026-07-31

新增表格：
  - knowledge_bases          KB 領域模型
  - knowledge_base_members    KB 成員與權限
  - knowledge_base_revisions  KB 版本修訂
  - document_artifacts        文件 artifact 追蹤
  - outbox_events             交易性 Outbox
  - projection_status         Projection 收斂狀態
  - sync_cursors              Connector 同步游標
  - dead_letter_events        失敗事件

修改表格：
  - documents: 新增 knowledge_base_id, source_system, source_record_id,
               external_version, content_hash, tombstoned_at
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = 'p0_kb_outbox_001'
down_revision: Union[str, None] = 'e2f3a4b5c6d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── knowledge_bases ──
    op.create_table(
        'knowledge_bases',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(), server_default='active'),
        sa.Column('policy_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('active_revision', sa.Integer(), server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    op.create_index('ix_knowledge_bases_tenant_id', 'knowledge_bases', ['tenant_id'])

    # ── knowledge_base_members ──
    op.create_table(
        'knowledge_base_members',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('kb_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('knowledge_bases.id'), nullable=False),
        sa.Column('subject_type', sa.String(), nullable=False),
        sa.Column('subject_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('role', sa.String(), nullable=False, server_default='reader'),
        sa.Column('effect', sa.String(), nullable=False, server_default='allow'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('kb_id', 'subject_type', 'subject_id', name='uq_kb_member_subject'),
    )
    op.create_index('ix_kb_members_kb_id', 'knowledge_base_members', ['kb_id'])
    op.create_index('ix_kb_members_subject_id', 'knowledge_base_members', ['subject_id'])

    # ── knowledge_base_revisions ──
    op.create_table(
        'knowledge_base_revisions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('kb_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('knowledge_bases.id'), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('manifest_hash', sa.String(), nullable=True),
        sa.Column('policy_revision', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('status', sa.String(), server_default='active'),
        sa.Column('change_summary', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('kb_id', 'revision', name='uq_kb_revision'),
    )
    op.create_index('ix_kb_revisions_kb_id', 'knowledge_base_revisions', ['kb_id'])

    # ── document_artifacts ──
    op.create_table(
        'document_artifacts',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('document_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('documents.id'), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('artifact_type', sa.String(), nullable=False),
        sa.Column('provider', sa.String(), nullable=False),
        sa.Column('provider_version', sa.String(), nullable=True),
        sa.Column('uri', sa.Text(), nullable=True),
        sa.Column('checksum', sa.String(), nullable=True),
        sa.Column('status', sa.String(), server_default='active'),
        sa.Column('metadata_json', postgresql.JSON(), server_default=sa.text("'{}'::json")),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    op.create_index('ix_doc_artifact_doc_id', 'document_artifacts', ['document_id'])
    op.create_index('ix_doc_artifact_provider', 'document_artifacts',
                    ['document_id', 'provider', 'artifact_type'])

    # ── outbox_events ──
    op.create_table(
        'outbox_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('aggregate_type', sa.String(), nullable=False),
        sa.Column('aggregate_id', sa.String(), nullable=False),
        sa.Column('event_type', sa.String(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('payload', postgresql.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column('idempotency_key', sa.String(), nullable=False),
        sa.Column('status', sa.String(), server_default='pending'),
        sa.Column('attempts', sa.Integer(), server_default='0'),
        sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.UniqueConstraint('idempotency_key', name='uq_outbox_idempotency'),
    )
    op.create_index('ix_outbox_aggregate_type', 'outbox_events', ['aggregate_type'])
    op.create_index('ix_outbox_aggregate_id', 'outbox_events', ['aggregate_id'])
    op.create_index('ix_outbox_status', 'outbox_events', ['status'])

    # ── projection_status ──
    op.create_table(
        'projection_status',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('resource_type', sa.String(), nullable=False),
        sa.Column('resource_id', sa.String(), nullable=False),
        sa.Column('provider', sa.String(), nullable=False),
        sa.Column('provider_instance_id', sa.String(), nullable=True),
        sa.Column('desired_revision', sa.Integer(), nullable=False),
        sa.Column('applied_revision', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('state', sa.String(), server_default='pending'),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('last_verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    op.create_index('ix_projection_resource', 'projection_status', ['resource_id'])

    # ── sync_cursors ──
    op.create_table(
        'sync_cursors',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('connector_instance_id', sa.String(), nullable=False),
        sa.Column('connector_type', sa.String(), nullable=False),
        sa.Column('cursor', sa.Text(), nullable=True),
        sa.Column('watermark', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_success_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('sync_state', postgresql.JSON(), server_default=sa.text("'{}'::json")),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.UniqueConstraint('connector_instance_id', name='uq_sync_cursor_instance'),
    )

    # ── dead_letter_events ──
    op.create_table(
        'dead_letter_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('original_event_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('aggregate_type', sa.String(), nullable=False),
        sa.Column('aggregate_id', sa.String(), nullable=False),
        sa.Column('event_type', sa.String(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('payload', postgresql.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column('attempts', sa.Integer(), server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_dlq_original_event', 'dead_letter_events', ['original_event_id'])

    # ── documents: 新增欄位 ──
    op.add_column('documents',
                  sa.Column('knowledge_base_id', postgresql.UUID(as_uuid=True),
                            sa.ForeignKey('knowledge_bases.id'), nullable=True))
    op.add_column('documents',
                  sa.Column('source_system', sa.String(), nullable=True))
    op.add_column('documents',
                  sa.Column('source_record_id', sa.String(), nullable=True))
    op.add_column('documents',
                  sa.Column('external_version', sa.String(), nullable=True))
    op.add_column('documents',
                  sa.Column('content_hash', sa.String(), nullable=True))
    op.add_column('documents',
                  sa.Column('tombstoned_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_documents_kb_id', 'documents', ['knowledge_base_id'])
    op.create_index('ix_documents_content_hash', 'documents', ['content_hash'])


def downgrade() -> None:
    # ── documents: 移除新增欄位 ──
    op.drop_index('ix_documents_content_hash', table_name='documents')
    op.drop_index('ix_documents_kb_id', table_name='documents')
    op.drop_column('documents', 'tombstoned_at')
    op.drop_column('documents', 'content_hash')
    op.drop_column('documents', 'external_version')
    op.drop_column('documents', 'source_record_id')
    op.drop_column('documents', 'source_system')
    op.drop_column('documents', 'knowledge_base_id')

    # ── 刪除新增表格 ──
    op.drop_table('dead_letter_events')
    op.drop_table('sync_cursors')
    op.drop_table('projection_status')
    op.drop_table('outbox_events')
    op.drop_table('document_artifacts')
    op.drop_table('knowledge_base_revisions')
    op.drop_table('knowledge_base_members')
    op.drop_table('knowledge_bases')
