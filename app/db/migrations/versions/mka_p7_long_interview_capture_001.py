"""Add durable, resumable long-form knowledge interview capture."""
import os
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "mka_p7_interview_capture_001"
down_revision: str | None = "mka_p6_task_events_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_TABLES = (
    "mka_knowledge_capture_sessions",
    "mka_knowledge_capture_chunks",
    "mka_knowledge_capture_transcript_segments",
)

_TENANT_POLICY = """
CREATE POLICY tenant_isolation ON "{table}"
  USING (
    tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
    OR current_setting('app.bypass_rls', true) = 'on'
  )
  WITH CHECK (
    tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
    OR current_setting('app.bypass_rls', true) = 'on'
  )
"""

_REQUIRED_COLUMNS = {
    "mka_knowledge_capture_sessions": {
        "id", "tenant_id", "owner_id", "title", "status", "consent_version",
        "consented_at", "received_chunks", "total_duration_ms", "created_at",
    },
    "mka_knowledge_capture_chunks": {
        "id", "tenant_id", "session_id", "sequence", "storage_key", "mime_type",
        "size_bytes", "sha256", "transcription_state", "created_at",
    },
    "mka_knowledge_capture_transcript_segments": {
        "id", "tenant_id", "session_id", "sequence", "start_ms", "end_ms",
        "raw_text", "created_at",
    },
}

_REQUIRED_INDEXES = {
    "mka_knowledge_capture_sessions": (
        ("ix_mka_knowledge_capture_sessions_tenant_id", ["tenant_id"]),
        ("ix_mka_knowledge_capture_sessions_owner_id", ["owner_id"]),
        ("ix_mka_knowledge_capture_sessions_status", ["status"]),
        ("ix_mka_capture_tenant_owner_status", ["tenant_id", "owner_id", "status"]),
    ),
    "mka_knowledge_capture_chunks": (
        ("ix_mka_knowledge_capture_chunks_tenant_id", ["tenant_id"]),
        ("ix_mka_knowledge_capture_chunks_session_id", ["session_id"]),
        ("ix_mka_capture_chunk_session_state", ["session_id", "transcription_state"]),
    ),
    "mka_knowledge_capture_transcript_segments": (
        ("ix_mka_knowledge_capture_transcript_segments_tenant_id", ["tenant_id"]),
        ("ix_mka_knowledge_capture_transcript_segments_session_id", ["session_id"]),
        ("ix_mka_knowledge_capture_transcript_segments_chunk_id", ["chunk_id"]),
        ("ix_mka_capture_segment_session_sequence", ["session_id", "sequence"]),
    ),
}


def _enable_rls() -> None:
    force = os.environ.get("RLS_ENFORCEMENT_ENABLED", "false").lower() == "true"
    for table in _TENANT_TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
        op.execute(_TENANT_POLICY.format(table=table))
        op.execute(f'ALTER TABLE "{table}" {"FORCE" if force else "NO FORCE"} ROW LEVEL SECURITY')


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names()) & set(_TENANT_TABLES)
    if existing:
        missing_tables = sorted(set(_TENANT_TABLES) - existing)
        if missing_tables:
            raise RuntimeError(
                "Cannot adopt partial long-interview schema; missing tables: "
                + ", ".join(missing_tables)
            )
        for table, required in _REQUIRED_COLUMNS.items():
            actual = {column["name"] for column in inspector.get_columns(table)}
            missing_columns = sorted(required - actual)
            if missing_columns:
                raise RuntimeError(
                    f"Cannot adopt pre-existing {table}; missing columns: "
                    + ", ".join(missing_columns)
                )
            indexes = {index["name"] for index in inspector.get_indexes(table)}
            for name, columns in _REQUIRED_INDEXES[table]:
                if name not in indexes:
                    op.create_index(name, table, columns)
        _enable_rls()
        return

    op.create_table(
        "mka_knowledge_capture_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("owner_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("equipment_id", sa.String(), nullable=True),
        sa.Column("interviewee", sa.String(), nullable=True),
        sa.Column("interviewer", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="recording"),
        sa.Column("consent_version", sa.String(), nullable=False, server_default="long-interview-v1"),
        sa.Column("consented_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("audio_policy_snapshot", sa.JSON(), nullable=True),
        sa.Column("transcript_policy_snapshot", sa.JSON(), nullable=True),
        sa.Column("expected_chunks", sa.Integer(), nullable=True),
        sa.Column("received_chunks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("transcript", sa.Text(), nullable=True),
        sa.Column("transcript_metadata", sa.JSON(), nullable=True),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.Column("audio_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("transcript_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_mka_knowledge_capture_sessions_tenant_id", "mka_knowledge_capture_sessions", ["tenant_id"])
    op.create_index("ix_mka_knowledge_capture_sessions_owner_id", "mka_knowledge_capture_sessions", ["owner_id"])
    op.create_index("ix_mka_knowledge_capture_sessions_status", "mka_knowledge_capture_sessions", ["status"])
    op.create_index("ix_mka_capture_tenant_owner_status", "mka_knowledge_capture_sessions", ["tenant_id", "owner_id", "status"])

    op.create_table(
        "mka_knowledge_capture_chunks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("session_id", UUID(as_uuid=True), sa.ForeignKey("mka_knowledge_capture_sessions.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("offset_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("storage_key", sa.String(), nullable=False),
        sa.Column("mime_type", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("transcription_state", sa.String(), nullable=False, server_default="pending"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "session_id", "sequence", name="uq_mka_capture_chunk_sequence"),
    )
    op.create_index("ix_mka_knowledge_capture_chunks_tenant_id", "mka_knowledge_capture_chunks", ["tenant_id"])
    op.create_index("ix_mka_knowledge_capture_chunks_session_id", "mka_knowledge_capture_chunks", ["session_id"])
    op.create_index("ix_mka_capture_chunk_session_state", "mka_knowledge_capture_chunks", ["session_id", "transcription_state"])

    op.create_table(
        "mka_knowledge_capture_transcript_segments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("session_id", UUID(as_uuid=True), sa.ForeignKey("mka_knowledge_capture_sessions.id"), nullable=False),
        sa.Column("chunk_id", UUID(as_uuid=True), sa.ForeignKey("mka_knowledge_capture_chunks.id"), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("speaker", sa.String(), nullable=True),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("corrected_text", sa.Text(), nullable=True),
        sa.Column("corrected_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("corrected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_mka_knowledge_capture_transcript_segments_tenant_id", "mka_knowledge_capture_transcript_segments", ["tenant_id"])
    op.create_index("ix_mka_knowledge_capture_transcript_segments_session_id", "mka_knowledge_capture_transcript_segments", ["session_id"])
    op.create_index("ix_mka_knowledge_capture_transcript_segments_chunk_id", "mka_knowledge_capture_transcript_segments", ["chunk_id"])
    op.create_index("ix_mka_capture_segment_session_sequence", "mka_knowledge_capture_transcript_segments", ["session_id", "sequence"])

    _enable_rls()


def downgrade() -> None:
    for table in reversed(_TENANT_TABLES):
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
    op.drop_table("mka_knowledge_capture_transcript_segments")
    op.drop_table("mka_knowledge_capture_chunks")
    op.drop_table("mka_knowledge_capture_sessions")
