"""Phase 2-7: connector, wiki, graph, policy deny, agent approval tables.

Revision ID: p2_full_plan_001
Revises: p1_gateway_resources_001
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "p2_full_plan_001"
down_revision: Union[str, None] = "p1_gateway_resources_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "connector_instances",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("connector_type", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), server_default="active"),
        sa.Column("config_json", sa.JSON(), server_default="{}"),
        sa.Column("credential_ref", sa.String(), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("sync_state", sa.JSON(), server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    op.create_index("ix_connector_instances_tenant", "connector_instances", ["tenant_id"])

    op.create_table(
        "external_principals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("principal_type", sa.String(), nullable=False),
        sa.Column("mapped_subject_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("mapped_subject_type", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "provider", "external_id", name="uq_external_principal"),
    )

    op.create_table(
        "source_acl_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("source_record_id", sa.String(), nullable=False),
        sa.Column("principal_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("external_principals.id"), nullable=False),
        sa.Column("permission", sa.String(), nullable=False),
        sa.Column("effect", sa.String(), server_default="allow"),
        sa.Column("inherited", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("revision", sa.Integer(), server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_source_acl_record", "source_acl_entries", ["tenant_id", "source_record_id"])

    op.create_table(
        "connector_resources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("connector_instance_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("connector_instances.id"), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("source_record_id", sa.String(), nullable=False),
        sa.Column("parent_source_id", sa.String(), nullable=True),
        sa.Column("source_version", sa.String(), nullable=True),
        sa.Column("content_hash", sa.String(), nullable=True),
        sa.Column("acl_hash", sa.String(), nullable=True),
        sa.Column("sync_state", sa.String(), server_default="synced"),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id"), nullable=True),
        sa.Column("metadata_json", sa.JSON(), server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.UniqueConstraint("connector_instance_id", "source_record_id", name="uq_connector_resource"),
    )

    op.create_table(
        "wiki_pages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("kb_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id"), nullable=True),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("page_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), server_default="draft"),
        sa.Column("active_revision", sa.Integer(), server_default="1"),
        sa.Column("provider", sa.String(), server_default="weknora"),
        sa.Column("provider_page_id", sa.String(), nullable=True),
        sa.Column("source_document_ids", sa.JSON(), server_default="[]"),
        sa.Column("backlinks", sa.JSON(), server_default="[]"),
        sa.Column("tombstoned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_wiki_slug"),
    )

    op.create_table(
        "wiki_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("wiki_page_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("wiki_pages.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=True),
        sa.Column("citation_map", sa.JSON(), server_default="[]"),
        sa.Column("compile_job_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("wiki_page_id", "revision", name="uq_wiki_revision"),
    )

    op.create_table(
        "graph_entities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("kb_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id"), nullable=True),
        sa.Column("namespace", sa.String(), server_default="weknora"),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("source_document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id"), nullable=True),
        sa.Column("source_revision", sa.Integer(), nullable=True),
        sa.Column("acl_fingerprint", sa.String(), nullable=True),
        sa.Column("provider_entity_id", sa.String(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), server_default="{}"),
        sa.Column("tombstoned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    op.create_index("ix_graph_entity_ns", "graph_entities", ["tenant_id", "namespace", "name"])

    op.create_table(
        "graph_edges",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("namespace", sa.String(), server_default="weknora"),
        sa.Column("source_entity_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("graph_entities.id"), nullable=False),
        sa.Column("target_entity_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("graph_entities.id"), nullable=False),
        sa.Column("relation_type", sa.String(), nullable=False),
        sa.Column("weight", sa.Integer(), server_default="1"),
        sa.Column("source_revision", sa.Integer(), nullable=True),
        sa.Column("acl_fingerprint", sa.String(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), server_default="{}"),
        sa.Column("tombstoned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "tenant_id", "namespace", "source_entity_id", "target_entity_id", "relation_type",
            name="uq_graph_edge",
        ),
    )

    op.create_table(
        "policy_deny_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("resource_type", sa.String(), nullable=False),
        sa.Column("resource_id", sa.String(), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("resource_type", "resource_id", "subject_id", name="uq_policy_deny"),
    )
    op.create_index("ix_policy_deny_resource", "policy_deny_entries", ["resource_type", "resource_id"])

    op.create_table(
        "agent_approval_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("tool_name", sa.String(), nullable=False),
        sa.Column("tool_risk", sa.String(), nullable=False),
        sa.Column("tool_category", sa.String(), nullable=True),
        sa.Column("action_summary", sa.Text(), nullable=False),
        sa.Column("target_system", sa.String(), nullable=True),
        sa.Column("impact_scope", sa.Text(), nullable=True),
        sa.Column("tool_args_json", sa.JSON(), server_default="{}"),
        sa.Column("policy_snapshot", sa.JSON(), server_default="{}"),
        sa.Column("status", sa.String(), server_default="pending"),
        sa.Column("approved_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("execution_result", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("agent_approval_requests")
    op.drop_index("ix_policy_deny_resource", table_name="policy_deny_entries")
    op.drop_table("policy_deny_entries")
    op.drop_table("graph_edges")
    op.drop_index("ix_graph_entity_ns", table_name="graph_entities")
    op.drop_table("graph_entities")
    op.drop_table("wiki_revisions")
    op.drop_table("wiki_pages")
    op.drop_table("connector_resources")
    op.drop_index("ix_source_acl_record", table_name="source_acl_entries")
    op.drop_table("source_acl_entries")
    op.drop_table("external_principals")
    op.drop_index("ix_connector_instances_tenant", table_name="connector_instances")
    op.drop_table("connector_instances")
