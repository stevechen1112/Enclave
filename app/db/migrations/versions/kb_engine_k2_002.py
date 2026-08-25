"""Reconcile installations that applied an early K1 development revision.

K1 was exercised locally before the branch was finalized.  Alembic identifies
revisions by id, so changing the body later cannot upgrade a database already
stamped at that id.  This forward-only compatibility migration makes those
installations converge with a fresh K1 database.  A fresh install safely no-ops.
"""
import os
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "kb_engine_k2_002"
down_revision: Union[str, None] = "kb_engine_k1_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RLS_TABLES = (
    "knowledge_base_revision_documents", "knowledge_policy_snapshots", "index_artifact_revisions",
    "knowledge_runtime_releases", "document_profiles", "knowledge_structured_tables",
    "knowledge_structured_rows", "knowledge_structured_fields", "knowledge_procedure_graphs",
    "knowledge_procedure_phases", "knowledge_entities", "knowledge_entity_aliases",
    "knowledge_releases", "knowledge_rollback_points", "knowledge_freshness_states",
    "knowledge_lexical_index",
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


def _columns(inspector, table: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table)}


def _indexes(inspector, table: str) -> set[str]:
    return {index["name"] for index in inspector.get_indexes(table)}


def _add(table: str, column: sa.Column) -> None:
    bind = op.get_bind(); inspector = sa.inspect(bind)
    if column.name not in _columns(inspector, table):
        op.add_column(table, column)


def upgrade() -> None:
    bind = op.get_bind()

    _add("knowhow_cards", sa.Column("review_due_at", sa.DateTime(timezone=True), nullable=True))
    _add("knowledge_base_revisions", sa.Column("manifest_json", sa.JSON(), nullable=False, server_default="{}"))
    _add("knowledge_base_revisions", sa.Column("index_namespace", sa.String(), nullable=True))
    _add("knowledge_base_revisions", sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True))

    chunk_had_revision = "document_revision" in _columns(sa.inspect(bind), "documentchunks")
    _add("documentchunks", sa.Column("document_revision", sa.Integer(), nullable=False, server_default="1"))
    if not chunk_had_revision:
        op.execute(
            "UPDATE documentchunks AS c SET document_revision = COALESCE(d.version, 1) "
            "FROM documents AS d WHERE d.id = c.document_id"
        )
        op.execute("DROP INDEX IF EXISTS uq_documentchunks_document_index")
        op.execute("DROP INDEX IF EXISTS uq_documentchunks_document_hash")
    inspector = sa.inspect(bind); chunk_indexes = _indexes(inspector, "documentchunks")
    if "uq_documentchunks_document_index" not in chunk_indexes:
        op.create_index("uq_documentchunks_document_index", "documentchunks", ["document_id", "document_revision", "chunk_index"], unique=True)
    if "uq_documentchunks_document_hash" not in chunk_indexes:
        op.create_index("uq_documentchunks_document_hash", "documentchunks", ["document_id", "document_revision", "chunk_hash"], unique=True,
                        postgresql_where=sa.text("chunk_hash IS NOT NULL"))
    if "ix_documentchunks_document_revision" not in chunk_indexes:
        op.create_index("ix_documentchunks_document_revision", "documentchunks", ["document_id", "document_revision"])

    gap_columns = [
        sa.Column("knowledge_base_revision_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_base_revisions.id"), nullable=True),
        sa.Column("owner_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("gap_type", sa.String(40), nullable=False, server_default="low_confidence"),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
    ]
    for column in gap_columns: _add("knowledgegaps", column)
    inspector = sa.inspect(bind); gap_indexes = _indexes(inspector, "knowledgegaps")
    if "ix_knowledgegaps_revision_id" not in gap_indexes:
        op.create_index("ix_knowledgegaps_revision_id", "knowledgegaps", ["knowledge_base_revision_id"])
    if "ix_knowledgegaps_owner_id" not in gap_indexes:
        op.create_index("ix_knowledgegaps_owner_id", "knowledgegaps", ["owner_id"])

    feedback_before = _columns(sa.inspect(bind), "chat_feedbacks")
    _add("chat_feedbacks", sa.Column("owner_id", UUID(as_uuid=True), nullable=True))
    _add("chat_feedbacks", sa.Column("status", sa.String(24), nullable=False, server_default="open"))
    _add("chat_feedbacks", sa.Column("processing_history", sa.JSON(), nullable=False, server_default="[]"))
    if "owner_id" not in feedback_before:
        op.execute("UPDATE chat_feedbacks SET owner_id = user_id WHERE owner_id IS NULL")
        op.alter_column("chat_feedbacks", "owner_id", nullable=False)
    inspector = sa.inspect(bind)
    fk_names = {foreign_key.get("name") for foreign_key in inspector.get_foreign_keys("chat_feedbacks")}
    if "fk_chat_feedback_owner" not in fk_names:
        op.create_foreign_key("fk_chat_feedback_owner", "chat_feedbacks", "users", ["owner_id"], ["id"])
    if "ix_chat_feedbacks_owner_id" not in _indexes(sa.inspect(bind), "chat_feedbacks"):
        op.create_index("ix_chat_feedbacks_owner_id", "chat_feedbacks", ["owner_id"])

    _add("knowledge_evaluation_runs", sa.Column("evaluation_key", sa.String(64), nullable=True))
    _add("knowledge_evaluation_runs", sa.Column("baseline_run_id", UUID(as_uuid=True), nullable=True))
    eval_cols = _columns(sa.inspect(bind), "knowledge_evaluation_runs")
    if "evaluation_key" in eval_cols:
        op.execute(
            "UPDATE knowledge_evaluation_runs SET evaluation_key = "
            "md5(split || ':' || corpus_hash || ':' || question_hash || ':' || scoring_hash) "
            "WHERE evaluation_key IS NULL"
        )
        op.execute(
            "WITH ranked AS ("
            " SELECT id, first_value(id) OVER (PARTITION BY evaluation_key ORDER BY created_at, id) AS baseline_id,"
            " row_number() OVER (PARTITION BY evaluation_key ORDER BY created_at, id) AS rn"
            " FROM knowledge_evaluation_runs WHERE first_run IS TRUE"
            ") UPDATE knowledge_evaluation_runs AS r"
            " SET first_run = FALSE, baseline_run_id = ranked.baseline_id"
            " FROM ranked WHERE r.id = ranked.id AND ranked.rn > 1"
        )
        op.alter_column("knowledge_evaluation_runs", "evaluation_key", nullable=False)
    inspector = sa.inspect(bind); eval_indexes = _indexes(inspector, "knowledge_evaluation_runs")
    if "ix_knowledge_evaluation_runs_evaluation_key" not in eval_indexes:
        op.create_index("ix_knowledge_evaluation_runs_evaluation_key", "knowledge_evaluation_runs", ["evaluation_key"])
    if "uq_knowledge_eval_first_run" not in eval_indexes:
        op.create_index("uq_knowledge_eval_first_run", "knowledge_evaluation_runs", ["evaluation_key"], unique=True,
                        postgresql_where=sa.text("first_run IS TRUE"))
    eval_fks = sa.inspect(bind).get_foreign_keys("knowledge_evaluation_runs")
    if not any(foreign_key.get("constrained_columns") == ["baseline_run_id"] for foreign_key in eval_fks):
        op.create_foreign_key("fk_knowledge_eval_baseline", "knowledge_evaluation_runs", "knowledge_evaluation_runs", ["baseline_run_id"], ["id"])

    _add("knowledge_procedure_phases", sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.true()))
    _add("knowledge_procedure_phases", sa.Column("completion_criteria", sa.Text(), nullable=True))

    # Early K1 installations had the tenant columns but not the DB-level PEP.
    # Recreate policies idempotently so app-level ACL is never the only layer.
    tables = set(sa.inspect(bind).get_table_names())
    force = os.environ.get("RLS_ENFORCEMENT_ENABLED", "false").lower() == "true"
    for table in _RLS_TABLES:
        if table not in tables:
            continue
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
        op.execute(_TENANT_POLICY.format(table=table))
        op.execute(f'ALTER TABLE "{table}" {"FORCE" if force else "NO FORCE"} ROW LEVEL SECURITY')


def downgrade() -> None:
    # K1's finalized schema owns these objects.  Removing them while K1 remains
    # stamped would recreate the exact drift this migration repairs.
    pass
