"""Normalize model/schema semantics after historical index-name drift.

Revision ID: schema_norm_k3_003
Revises: kb_engine_k2_002

This migration only adds indexes declared by the ORM and closes two nullable
namespace gaps.  Partial/NULLS-NOT-DISTINCT unique indexes from DD-M04 are
preserved and represented directly in model metadata.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "schema_norm_k3_003"
down_revision: str | None = "kb_engine_k2_002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_INDEXES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("ix_agent_approval_requests_actor_id", "agent_approval_requests", ("actor_id",)),
    ("ix_agent_approval_requests_tenant_id", "agent_approval_requests", ("tenant_id",)),
    ("ix_connector_resources_connector_instance_id", "connector_resources", ("connector_instance_id",)),
    ("ix_connector_resources_source_record_id", "connector_resources", ("source_record_id",)),
    ("ix_connector_resources_tenant_id", "connector_resources", ("tenant_id",)),
    ("ix_external_principals_mapped_subject_id", "external_principals", ("mapped_subject_id",)),
    ("ix_external_principals_tenant_id", "external_principals", ("tenant_id",)),
    ("ix_graph_edges_source_entity_id", "graph_edges", ("source_entity_id",)),
    ("ix_graph_edges_target_entity_id", "graph_edges", ("target_entity_id",)),
    ("ix_graph_edges_tenant_id", "graph_edges", ("tenant_id",)),
    ("ix_graph_entities_kb_id", "graph_entities", ("kb_id",)),
    ("ix_graph_entities_name", "graph_entities", ("name",)),
    ("ix_graph_entities_tenant_id", "graph_entities", ("tenant_id",)),
    ("ix_policy_deny_entries_resource_id", "policy_deny_entries", ("resource_id",)),
    ("ix_policy_deny_entries_subject_id", "policy_deny_entries", ("subject_id",)),
    ("ix_policy_deny_entries_tenant_id", "policy_deny_entries", ("tenant_id",)),
    ("ix_source_acl_entries_source_record_id", "source_acl_entries", ("source_record_id",)),
    ("ix_source_acl_entries_tenant_id", "source_acl_entries", ("tenant_id",)),
    ("ix_wiki_pages_kb_id", "wiki_pages", ("kb_id",)),
    ("ix_wiki_pages_slug", "wiki_pages", ("slug",)),
    ("ix_wiki_pages_tenant_id", "wiki_pages", ("tenant_id",)),
    ("ix_wiki_revisions_wiki_page_id", "wiki_revisions", ("wiki_page_id",)),
)


def upgrade() -> None:
    # Historical rows may predate the non-null model contract.
    op.execute("UPDATE graph_entities SET namespace = 'weknora' WHERE namespace IS NULL")
    op.execute("UPDATE graph_edges SET namespace = 'weknora' WHERE namespace IS NULL")
    op.alter_column("graph_entities", "namespace", existing_type=sa.String(), nullable=False)
    op.alter_column("graph_edges", "namespace", existing_type=sa.String(), nullable=False)

    for name, table, columns in _INDEXES:
        op.create_index(name, table, list(columns), unique=False)


def downgrade() -> None:
    for name, table, _columns in reversed(_INDEXES):
        op.drop_index(name, table_name=table)
    op.alter_column("graph_edges", "namespace", existing_type=sa.String(), nullable=True)
    op.alter_column("graph_entities", "namespace", existing_type=sa.String(), nullable=True)
