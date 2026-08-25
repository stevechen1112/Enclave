"""Knowledge execution foundation: immutable revisions, readiness and lineage."""
import os
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "kb_engine_k1_001"
down_revision: str | None = "mka_p7_interview_capture_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RLS_TABLES = (
    "knowledge_base_revision_documents", "knowledge_policy_snapshots", "index_artifact_revisions",
    "knowledge_runtime_releases", "document_profiles", "knowledge_structured_tables",
    "knowledge_structured_rows", "knowledge_structured_fields", "knowledge_procedure_graphs",
    "knowledge_procedure_phases", "knowledge_entities", "knowledge_entity_aliases",
    "knowledge_releases", "knowledge_rollback_points", "knowledge_freshness_states",
    "knowledge_lexical_index",
)
_K1_CREATED_TABLES = _RLS_TABLES + (
    "knowledge_evaluation_runs",
    "knowledge_evaluation_case_results",
    "knowledge_evaluation_human_reviews",
)
_K1_REQUIRED_COLUMNS = {
    "knowledge_base_revision_documents": {"id", "tenant_id", "kb_revision_id", "document_id", "document_version_id", "document_revision"},
    "knowledge_policy_snapshots": {"id", "tenant_id", "kb_id", "revision", "policy_hash"},
    "index_artifact_revisions": {"id", "tenant_id", "kb_revision_id", "artifact_type", "namespace", "artifact_hash"},
    "knowledge_runtime_releases": {"id", "tenant_id", "kb_revision_id", "image_digest", "prompt_hash", "status"},
    "document_profiles": {"id", "tenant_id", "document_id", "document_revision", "format_family", "content_hash"},
    "knowledge_structured_tables": {"id", "tenant_id", "document_id", "document_revision", "table_key", "content_hash"},
    "knowledge_structured_rows": {"id", "tenant_id", "table_id", "row_key", "row_number", "row_hash"},
    "knowledge_structured_fields": {"id", "tenant_id", "row_id", "field_name", "value_type"},
    "knowledge_procedure_graphs": {"id", "tenant_id", "document_id", "document_revision", "title", "content_hash"},
    "knowledge_procedure_phases": {"id", "tenant_id", "graph_id", "phase_key", "sequence", "instruction"},
    "knowledge_entities": {"id", "tenant_id", "entity_type", "canonical_key", "display_name"},
    "knowledge_entity_aliases": {"id", "tenant_id", "entity_id", "alias", "alias_normalized"},
    "knowledge_releases": {"id", "tenant_id", "kb_id", "kb_revision_id", "status"},
    "knowledge_rollback_points": {"id", "tenant_id", "kb_id", "from_release_id", "to_release_id", "reason"},
    "knowledge_evaluation_runs": {"id", "tenant_id", "split", "corpus_hash", "question_hash", "scoring_hash", "first_run"},
    "knowledge_evaluation_case_results": {"id", "run_id", "case_id", "domain", "case_type", "verdict"},
    "knowledge_evaluation_human_reviews": {"id", "case_result_id", "reviewer_id", "original_verdict", "final_verdict", "reason"},
    "knowledge_freshness_states": {"id", "tenant_id", "document_id", "state"},
    "knowledge_lexical_index": {"chunk_id", "tenant_id", "document_id", "document_revision", "tokens", "content_hash"},
}
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


def _enable_rls() -> None:
    force = os.environ.get("RLS_ENFORCEMENT_ENABLED", "false").lower() == "true"
    for table in _RLS_TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
        op.execute(_TENANT_POLICY.format(table=table))
        op.execute(f'ALTER TABLE "{table}" {"FORCE" if force else "NO FORCE"} ROW LEVEL SECURITY')


def _id():
    return sa.Column("id", UUID(as_uuid=True), primary_key=True)


def _tenant():
    return sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing_k1 = set(inspector.get_table_names()) & set(_K1_CREATED_TABLES)
    if existing_k1 and existing_k1 != set(_K1_CREATED_TABLES):
        missing = sorted(set(_K1_CREATED_TABLES) - existing_k1)
        raise RuntimeError(
            "Cannot adopt partial pre-existing K1 schema; missing tables: "
            + ", ".join(missing)
        )
    adopt_preexisting = bool(existing_k1)

    op.add_column("knowhow_cards", sa.Column("review_due_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("knowledgegaps", sa.Column("knowledge_base_revision_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_base_revisions.id"), nullable=True))
    op.add_column("knowledgegaps", sa.Column("owner_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True))
    op.add_column("knowledgegaps", sa.Column("gap_type", sa.String(40), nullable=False, server_default="low_confidence"))
    op.add_column("knowledgegaps", sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("knowledgegaps", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()))
    op.create_index("ix_knowledgegaps_revision_id", "knowledgegaps", ["knowledge_base_revision_id"])
    op.create_index("ix_knowledgegaps_owner_id", "knowledgegaps", ["owner_id"])
    op.add_column("documentchunks", sa.Column("document_revision", sa.Integer(), nullable=False, server_default="1"))
    op.execute(
        "UPDATE documentchunks AS c SET document_revision = COALESCE(d.version, 1) "
        "FROM documents AS d WHERE d.id = c.document_id"
    )
    op.execute("DROP INDEX IF EXISTS uq_documentchunks_document_index")
    op.execute("DROP INDEX IF EXISTS uq_documentchunks_document_hash")
    op.create_index("uq_documentchunks_document_index", "documentchunks", ["document_id", "document_revision", "chunk_index"], unique=True)
    op.create_index("uq_documentchunks_document_hash", "documentchunks", ["document_id", "document_revision", "chunk_hash"], unique=True,
                    postgresql_where=sa.text("chunk_hash IS NOT NULL"))
    op.create_index("ix_documentchunks_document_revision", "documentchunks", ["document_id", "document_revision"])
    op.add_column("chat_feedbacks", sa.Column("owner_id", UUID(as_uuid=True), nullable=True))
    op.add_column("chat_feedbacks", sa.Column("status", sa.String(24), nullable=False, server_default="open"))
    op.add_column("chat_feedbacks", sa.Column("processing_history", sa.JSON(), nullable=False, server_default="[]"))
    op.create_foreign_key("fk_chat_feedback_owner", "chat_feedbacks", "users", ["owner_id"], ["id"])
    op.execute("UPDATE chat_feedbacks SET owner_id = user_id WHERE owner_id IS NULL")
    op.alter_column("chat_feedbacks", "owner_id", nullable=False)
    op.create_index("ix_chat_feedbacks_owner_id", "chat_feedbacks", ["owner_id"])
    op.add_column("knowledge_base_revisions", sa.Column("manifest_json", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("knowledge_base_revisions", sa.Column("index_namespace", sa.String(), nullable=True))
    op.add_column("knowledge_base_revisions", sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True))

    if adopt_preexisting:
        inspector = sa.inspect(op.get_bind())
        for table, required in _K1_REQUIRED_COLUMNS.items():
            actual = {column["name"] for column in inspector.get_columns(table)}
            missing_columns = sorted(required - actual)
            if missing_columns:
                raise RuntimeError(
                    f"Cannot adopt pre-existing {table}; missing columns: "
                    + ", ".join(missing_columns)
                )
        _enable_rls()
        return

    op.create_table("knowledge_base_revision_documents", _id(), _tenant(),
        sa.Column("kb_revision_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_base_revisions.id"), nullable=False),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("document_version_id", UUID(as_uuid=True), sa.ForeignKey("documentversions.id"), nullable=False),
        sa.Column("document_revision", sa.Integer(), nullable=False), sa.Column("content_hash", sa.String(128), nullable=False),
        sa.Column("acl_snapshot", sa.JSON(), nullable=False, server_default="{}"), sa.Column("policy_revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("kb_revision_id", "document_id", name="uq_kb_revision_document"),
        sa.UniqueConstraint("kb_revision_id", "document_version_id", name="uq_kb_revision_document_version"))
    op.create_index("ix_knowledge_base_revision_documents_tenant_id", "knowledge_base_revision_documents", ["tenant_id"])
    op.create_index("ix_knowledge_base_revision_documents_kb_revision_id", "knowledge_base_revision_documents", ["kb_revision_id"])
    op.create_index("ix_knowledge_base_revision_documents_document_id", "knowledge_base_revision_documents", ["document_id"])
    op.create_index("ix_knowledge_base_revision_documents_document_version_id", "knowledge_base_revision_documents", ["document_version_id"])

    op.create_table("knowledge_policy_snapshots", _id(), _tenant(), sa.Column("kb_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False), sa.Column("policy_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("policy_hash", sa.String(64), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("kb_id", "revision", name="uq_kb_policy_snapshot"))
    op.create_index("ix_knowledge_policy_snapshots_tenant_id", "knowledge_policy_snapshots", ["tenant_id"])
    op.create_index("ix_knowledge_policy_snapshots_kb_id", "knowledge_policy_snapshots", ["kb_id"])

    op.create_table("index_artifact_revisions", _id(), _tenant(), sa.Column("kb_revision_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_base_revisions.id"), nullable=False),
        sa.Column("artifact_type", sa.String(40), nullable=False), sa.Column("namespace", sa.String(255), nullable=False),
        sa.Column("version_manifest", sa.JSON(), nullable=False, server_default="{}"), sa.Column("artifact_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="ready"), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("kb_revision_id", "artifact_type", "namespace", name="uq_kb_index_artifact"))
    op.create_index("ix_index_artifact_revisions_tenant_id", "index_artifact_revisions", ["tenant_id"])
    op.create_index("ix_index_artifact_revisions_kb_revision_id", "index_artifact_revisions", ["kb_revision_id"])

    op.create_table("knowledge_runtime_releases", _id(), _tenant(), sa.Column("kb_revision_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_base_revisions.id"), nullable=False),
        sa.Column("image_digest", sa.String(255), nullable=False), sa.Column("model_manifest", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("prompt_hash", sa.String(64), nullable=False), sa.Column("feature_flags", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("rollout_percent", sa.Integer(), nullable=False, server_default="0"), sa.Column("status", sa.String(24), nullable=False, server_default="candidate"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index("ix_knowledge_runtime_releases_tenant_id", "knowledge_runtime_releases", ["tenant_id"])
    op.create_index("ix_knowledge_runtime_releases_kb_revision_id", "knowledge_runtime_releases", ["kb_revision_id"])

    op.create_table("document_profiles", _id(), _tenant(), sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("document_revision", sa.Integer(), nullable=False), sa.Column("format_family", sa.String(40), nullable=False),
        sa.Column("support_level", sa.String(24), nullable=False), sa.Column("language_profile", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("page_count", sa.Integer(), nullable=True), sa.Column("structure_map", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("capability_readiness", sa.JSON(), nullable=False, server_default="{}"), sa.Column("warnings", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("quality_score", sa.Float(), nullable=True), sa.Column("answer_ready", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("profiler_version", sa.String(40), nullable=False), sa.Column("content_hash", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("document_id", "document_revision", name="uq_document_profile_revision"))
    op.create_index("ix_document_profiles_tenant_id", "document_profiles", ["tenant_id"])
    op.create_index("ix_document_profiles_document_id", "document_profiles", ["document_id"])
    op.create_index("ix_document_profile_ready", "document_profiles", ["tenant_id", "answer_ready"])

    op.create_table("knowledge_structured_tables", _id(), _tenant(), sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("document_revision", sa.Integer(), nullable=False), sa.Column("worksheet", sa.String(255), nullable=True), sa.Column("table_key", sa.String(255), nullable=False),
        sa.Column("headers", sa.JSON(), nullable=False, server_default="[]"), sa.Column("page", sa.Integer(), nullable=True), sa.Column("bbox", sa.JSON(), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("document_id", "document_revision", "table_key", name="uq_structured_table_key"))
    op.create_index("ix_knowledge_structured_tables_tenant_id", "knowledge_structured_tables", ["tenant_id"])
    op.create_index("ix_knowledge_structured_tables_document_id", "knowledge_structured_tables", ["document_id"])
    op.create_table("knowledge_structured_rows", _id(), _tenant(), sa.Column("table_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_structured_tables.id"), nullable=False),
        sa.Column("row_key", sa.String(255), nullable=False), sa.Column("row_number", sa.Integer(), nullable=False), sa.Column("identity_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("row_hash", sa.String(64), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("table_id", "row_key", name="uq_structured_row_key"))
    op.create_index("ix_knowledge_structured_rows_tenant_id", "knowledge_structured_rows", ["tenant_id"])
    op.create_index("ix_knowledge_structured_rows_table_id", "knowledge_structured_rows", ["table_id"])
    op.create_table("knowledge_structured_fields", _id(), _tenant(), sa.Column("row_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_structured_rows.id"), nullable=False),
        sa.Column("field_name", sa.String(255), nullable=False), sa.Column("raw_value", sa.Text(), nullable=True), sa.Column("normalized_value", sa.JSON(), nullable=True),
        sa.Column("value_type", sa.String(32), nullable=False, server_default="text"), sa.Column("unit", sa.String(32), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1"), sa.Column("bbox", sa.JSON(), nullable=True),
        sa.UniqueConstraint("row_id", "field_name", name="uq_structured_row_field"))
    op.create_index("ix_knowledge_structured_fields_tenant_id", "knowledge_structured_fields", ["tenant_id"])
    op.create_index("ix_knowledge_structured_fields_row_id", "knowledge_structured_fields", ["row_id"])

    op.create_table("knowledge_procedure_graphs", _id(), _tenant(), sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("document_revision", sa.Integer(), nullable=False), sa.Column("title", sa.String(500), nullable=False), sa.Column("scope_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("risk_class", sa.String(24), nullable=False, server_default="normal"), sa.Column("content_hash", sa.String(64), nullable=False),
        sa.UniqueConstraint("document_id", "document_revision", "title", name="uq_procedure_graph"))
    op.create_index("ix_knowledge_procedure_graphs_tenant_id", "knowledge_procedure_graphs", ["tenant_id"])
    op.create_index("ix_knowledge_procedure_graphs_document_id", "knowledge_procedure_graphs", ["document_id"])
    op.create_table("knowledge_procedure_phases", _id(), _tenant(), sa.Column("graph_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_procedure_graphs.id"), nullable=False),
        sa.Column("phase_key", sa.String(120), nullable=False), sa.Column("sequence", sa.Integer(), nullable=False), sa.Column("actor", sa.String(255), nullable=True),
        sa.Column("instruction", sa.Text(), nullable=False), sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("completion_criteria", sa.Text(), nullable=True), sa.Column("condition_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("exception_json", sa.JSON(), nullable=False, server_default="{}"), sa.Column("input_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("output_json", sa.JSON(), nullable=False, server_default="[]"), sa.Column("next_phase_keys", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("source_ref", sa.JSON(), nullable=False, server_default="{}"), sa.UniqueConstraint("graph_id", "phase_key", name="uq_procedure_phase"))
    op.create_index("ix_knowledge_procedure_phases_tenant_id", "knowledge_procedure_phases", ["tenant_id"])
    op.create_index("ix_knowledge_procedure_phases_graph_id", "knowledge_procedure_phases", ["graph_id"])

    op.create_table("knowledge_entities", _id(), _tenant(), sa.Column("entity_type", sa.String(80), nullable=False), sa.Column("canonical_key", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(500), nullable=False), sa.Column("attributes_json", sa.JSON(), nullable=False, server_default="{}"), sa.Column("status", sa.String(24), nullable=False, server_default="active"),
        sa.UniqueConstraint("tenant_id", "entity_type", "canonical_key", name="uq_tenant_entity"))
    op.create_index("ix_knowledge_entities_tenant_id", "knowledge_entities", ["tenant_id"])
    op.create_table("knowledge_entity_aliases", _id(), _tenant(), sa.Column("entity_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_entities.id"), nullable=False),
        sa.Column("alias", sa.String(500), nullable=False), sa.Column("alias_normalized", sa.String(500), nullable=False), sa.Column("source_ref", sa.JSON(), nullable=True),
        sa.Column("approved", sa.Boolean(), nullable=False, server_default=sa.false()), sa.UniqueConstraint("tenant_id", "alias_normalized", "entity_id", name="uq_tenant_entity_alias"))
    op.create_index("ix_knowledge_entity_aliases_tenant_id", "knowledge_entity_aliases", ["tenant_id"])
    op.create_index("ix_knowledge_entity_aliases_entity_id", "knowledge_entity_aliases", ["entity_id"])

    op.create_table("knowledge_releases", _id(), _tenant(), sa.Column("kb_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id"), nullable=False),
        sa.Column("kb_revision_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_base_revisions.id"), nullable=False),
        sa.Column("runtime_release_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_runtime_releases.id"), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="candidate"), sa.Column("gate_evidence", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index("ix_knowledge_releases_tenant_id", "knowledge_releases", ["tenant_id"])
    op.create_index("ix_knowledge_releases_kb_id", "knowledge_releases", ["kb_id"])
    op.create_table("knowledge_rollback_points", _id(), _tenant(), sa.Column("kb_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id"), nullable=False),
        sa.Column("from_release_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_releases.id"), nullable=False),
        sa.Column("to_release_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_releases.id"), nullable=False), sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("executed_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index("ix_knowledge_rollback_points_tenant_id", "knowledge_rollback_points", ["tenant_id"])
    op.create_index("ix_knowledge_rollback_points_kb_id", "knowledge_rollback_points", ["kb_id"])

    op.create_table("knowledge_evaluation_runs", _id(),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("split", sa.String(40), nullable=False), sa.Column("evaluation_key", sa.String(64), nullable=False),
        sa.Column("corpus_hash", sa.String(64), nullable=False),
        sa.Column("question_hash", sa.String(64), nullable=False), sa.Column("scoring_hash", sa.String(64), nullable=False),
        sa.Column("runtime_manifest", sa.JSON(), nullable=False, server_default="{}"), sa.Column("status", sa.String(24), nullable=False, server_default="running"),
        sa.Column("first_run", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("baseline_run_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_evaluation_runs.id"), nullable=True),
        sa.Column("summary_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_knowledge_evaluation_runs_tenant_id", "knowledge_evaluation_runs", ["tenant_id"])
    op.create_index("ix_knowledge_evaluation_runs_evaluation_key", "knowledge_evaluation_runs", ["evaluation_key"])
    op.create_index("uq_knowledge_eval_first_run", "knowledge_evaluation_runs", ["evaluation_key"], unique=True,
                    postgresql_where=sa.text("first_run IS TRUE"))
    op.create_table("knowledge_evaluation_case_results", _id(), sa.Column("run_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_evaluation_runs.id"), nullable=False),
        sa.Column("case_id", sa.String(255), nullable=False), sa.Column("domain", sa.String(80), nullable=False), sa.Column("case_type", sa.String(80), nullable=False),
        sa.Column("verdict", sa.String(24), nullable=False), sa.Column("critical_error", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("metrics_json", sa.JSON(), nullable=False, server_default="{}"), sa.Column("evidence_digest", sa.String(64), nullable=True),
        sa.UniqueConstraint("run_id", "case_id", name="uq_evaluation_run_case"))
    op.create_index("ix_knowledge_evaluation_case_results_run_id", "knowledge_evaluation_case_results", ["run_id"])
    op.create_table("knowledge_evaluation_human_reviews", _id(), sa.Column("case_result_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_evaluation_case_results.id"), nullable=False),
        sa.Column("reviewer_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False), sa.Column("original_verdict", sa.String(24), nullable=False),
        sa.Column("final_verdict", sa.String(24), nullable=False), sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index("ix_knowledge_evaluation_human_reviews_case_result_id", "knowledge_evaluation_human_reviews", ["case_result_id"])
    op.create_table("knowledge_freshness_states", _id(), _tenant(), sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("review_due_at", sa.DateTime(timezone=True), nullable=True), sa.Column("last_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("upstream_sync_at", sa.DateTime(timezone=True), nullable=True), sa.Column("state", sa.String(24), nullable=False, server_default="current"),
        sa.Column("owner_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True), sa.Column("reasons", sa.JSON(), nullable=False, server_default="[]"),
        sa.UniqueConstraint("document_id", name="uq_document_freshness_state"))
    op.create_index("ix_knowledge_freshness_states_tenant_id", "knowledge_freshness_states", ["tenant_id"])
    op.create_index("ix_knowledge_freshness_states_document_id", "knowledge_freshness_states", ["document_id"])
    op.create_table("knowledge_lexical_index",
        sa.Column("chunk_id", UUID(as_uuid=True), sa.ForeignKey("documentchunks.id"), primary_key=True), _tenant(),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("document_revision", sa.Integer(), nullable=False), sa.Column("tokens", sa.ARRAY(sa.String()), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False), sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("index_version", sa.String(32), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index("ix_knowledge_lexical_index_tenant_id", "knowledge_lexical_index", ["tenant_id"])
    op.create_index("ix_knowledge_lexical_index_document_id", "knowledge_lexical_index", ["document_id"])
    op.create_index("ix_knowledge_lexical_tokens_gin", "knowledge_lexical_index", ["tokens"], postgresql_using="gin")
    _enable_rls()


def downgrade() -> None:
    for table in _RLS_TABLES:
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
    for table in (
        "knowledge_lexical_index", "knowledge_freshness_states", "knowledge_evaluation_human_reviews", "knowledge_evaluation_case_results", "knowledge_evaluation_runs",
        "knowledge_rollback_points", "knowledge_releases", "knowledge_entity_aliases", "knowledge_entities",
        "knowledge_procedure_phases", "knowledge_procedure_graphs", "knowledge_structured_fields", "knowledge_structured_rows",
        "knowledge_structured_tables", "document_profiles", "knowledge_runtime_releases", "index_artifact_revisions",
        "knowledge_policy_snapshots", "knowledge_base_revision_documents",
    ):
        op.drop_table(table)
    op.drop_column("knowledge_base_revisions", "activated_at")
    op.drop_column("knowledge_base_revisions", "index_namespace")
    op.drop_column("knowledge_base_revisions", "manifest_json")
    op.drop_index("ix_documentchunks_document_revision", table_name="documentchunks")
    op.drop_index("uq_documentchunks_document_hash", table_name="documentchunks")
    op.drop_index("uq_documentchunks_document_index", table_name="documentchunks")
    op.create_index("uq_documentchunks_document_index", "documentchunks", ["document_id", "chunk_index"], unique=True)
    op.create_index("uq_documentchunks_document_hash", "documentchunks", ["document_id", "chunk_hash"], unique=True,
                    postgresql_where=sa.text("chunk_hash IS NOT NULL"))
    op.drop_column("documentchunks", "document_revision")
    op.drop_column("knowhow_cards", "review_due_at")
    op.drop_index("ix_knowledgegaps_owner_id", table_name="knowledgegaps")
    op.drop_index("ix_knowledgegaps_revision_id", table_name="knowledgegaps")
    op.drop_column("knowledgegaps", "last_seen_at")
    op.drop_column("knowledgegaps", "occurrence_count")
    op.drop_column("knowledgegaps", "gap_type")
    op.drop_column("knowledgegaps", "owner_id")
    op.drop_column("knowledgegaps", "knowledge_base_revision_id")
    op.drop_index("ix_chat_feedbacks_owner_id", table_name="chat_feedbacks")
    op.drop_constraint("fk_chat_feedback_owner", "chat_feedbacks", type_="foreignkey")
    op.drop_column("chat_feedbacks", "processing_history")
    op.drop_column("chat_feedbacks", "status")
    op.drop_column("chat_feedbacks", "owner_id")
