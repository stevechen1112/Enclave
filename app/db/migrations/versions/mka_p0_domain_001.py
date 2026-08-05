"""MKA domain models — JobModule, InteractionSession, FormDefinition, FormInstance, RuleSet, ApprovalPolicy, KnowhowCard, TenantTermDictionary."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "mka_p0_domain_001"
down_revision: Union[str, None] = "p7_rls_new_tables_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # JobModule
    op.create_table(
        "job_modules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("module_key", sa.String, nullable=False, index=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=True, index=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("version", sa.String, default="1.0"),
        sa.Column("status", sa.String, default="draft"),
        sa.Column("allowed_roles", sa.JSON, default=list),
        sa.Column("allowed_departments", sa.JSON, default=list),
        sa.Column("knowledge_scope_policy", sa.JSON, default=dict),
        sa.Column("supported_intents", sa.JSON, default=list),
        sa.Column("allowed_tools", sa.JSON, default=list),
        sa.Column("form_definition_ids", sa.JSON, default=list),
        sa.Column("approval_policy_id", UUID(as_uuid=True), nullable=True),
        sa.Column("ux_entrypoints", sa.JSON, default=list),
        sa.Column("metrics_config", sa.JSON, default=dict),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.UniqueConstraint("module_key", "tenant_id", name="uq_job_module_key_tenant"),
    )

    # TenantModuleBinding
    op.create_table(
        "tenant_module_bindings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("module_key", sa.String, nullable=False, index=True),
        sa.Column("module_version", sa.String, default="1.0"),
        sa.Column("enabled", sa.Boolean, default=False),
        sa.Column("license_state", sa.String, default="trial"),
        sa.Column("config_json", sa.JSON, default=dict),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "module_key", name="uq_tenant_module_binding"),
    )

    # InteractionSession
    op.create_table(
        "interaction_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("module_key", sa.String, nullable=True),
        sa.Column("channel", sa.String, default="web"),
        sa.Column("scene_context", sa.JSON, default=dict),
        sa.Column("transcript", sa.Text, nullable=True),
        sa.Column("transcript_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("detected_fields", sa.JSON, default=dict),
        sa.Column("pending_questions", sa.JSON, default=list),
        sa.Column("risk_level", sa.String, default="low"),
        sa.Column("state", sa.String, default="active"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )

    # TenantTermDictionary
    op.create_table(
        "tenant_term_dictionaries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("term", sa.String, nullable=False),
        sa.Column("aliases", sa.JSON, default=list),
        sa.Column("phonetic_hints", sa.JSON, default=list),
        sa.Column("category", sa.String, default="general"),
        sa.Column("scope", sa.String, default="global"),
        sa.Column("active", sa.Boolean, default=True),
        sa.Column("source", sa.String, nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "term", name="uq_tenant_term"),
    )
    op.create_index("ix_tenant_term_category", "tenant_term_dictionaries", ["tenant_id", "category"])

    # FormDefinition
    op.create_table(
        "form_definitions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=True, index=True),
        sa.Column("form_key", sa.String, nullable=False, index=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("schema_version", sa.String, default="1.0"),
        sa.Column("json_schema", sa.JSON, default=dict),
        sa.Column("ui_schema", sa.JSON, default=dict),
        sa.Column("output_templates", sa.JSON, default=list),
        sa.Column("rule_set_id", UUID(as_uuid=True), nullable=True),
        sa.Column("approval_policy_id", UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String, default="draft"),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.UniqueConstraint("form_key", "tenant_id", "schema_version", name="uq_form_def_key_tenant_version"),
    )

    # FormInstance
    op.create_table(
        "form_instances",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("form_definition_id", UUID(as_uuid=True), sa.ForeignKey("form_definitions.id"), nullable=False, index=True),
        sa.Column("form_version", sa.String, default="1.0"),
        sa.Column("module_key", sa.String, nullable=True),
        sa.Column("owner_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("status", sa.String, default="draft"),
        sa.Column("values_json", sa.JSON, default=dict),
        sa.Column("provenance_json", sa.JSON, default=dict),
        sa.Column("calculation_snapshot", sa.JSON, default=dict),
        sa.Column("validation_result", sa.JSON, default=dict),
        sa.Column("source_document_ids", sa.JSON, default=list),
        sa.Column("scene_context", sa.JSON, default=dict),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
    )

    # RuleSet
    op.create_table(
        "rule_sets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=True, index=True),
        sa.Column("rule_key", sa.String, nullable=False, index=True),
        sa.Column("version", sa.String, default="1.0"),
        sa.Column("input_schema", sa.JSON, default=dict),
        sa.Column("output_schema", sa.JSON, default=dict),
        sa.Column("implementation_ref", sa.String, nullable=True),
        sa.Column("test_cases", sa.JSON, default=list),
        sa.Column("status", sa.String, default="draft"),
        sa.Column("approved_by", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.UniqueConstraint("rule_key", "tenant_id", "version", name="uq_rule_set_key_tenant_version"),
    )

    # ApprovalPolicy
    op.create_table(
        "approval_policies",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=True, index=True),
        sa.Column("module_key", sa.String, nullable=True),
        sa.Column("object_type", sa.String, nullable=False),
        sa.Column("risk_level", sa.String, default="medium"),
        sa.Column("steps", sa.JSON, default=list),
        sa.Column("timeout_policy", sa.JSON, default=dict),
        sa.Column("delegation_policy", sa.JSON, default=dict),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )

    # MKA ApprovalRequest
    op.create_table(
        "mka_approval_requests",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("object_type", sa.String, nullable=False),
        sa.Column("object_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("policy_version", sa.String, default="1.0"),
        sa.Column("current_step", sa.Integer, default=0),
        sa.Column("status", sa.String, default="pending"),
        sa.Column("submitted_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reviewers", sa.JSON, default=list),
        sa.Column("decision_log", sa.JSON, default=list),
        sa.Column("immutable_snapshot", sa.JSON, default=dict),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )

    # KnowhowCard
    op.create_table(
        "knowhow_cards",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("title", sa.String, nullable=False),
        sa.Column("status", sa.String, default="draft"),
        sa.Column("authority_level", sa.Integer, default=60),
        sa.Column("applicable_roles", sa.JSON, default=list),
        sa.Column("equipment_ids", sa.JSON, default=list),
        sa.Column("product_ids", sa.JSON, default=list),
        sa.Column("customer_ids", sa.JSON, default=list),
        sa.Column("problem_context", sa.Text, nullable=True),
        sa.Column("recommended_actions", sa.JSON, default=list),
        sa.Column("prerequisites", sa.JSON, default=list),
        sa.Column("risks", sa.JSON, default=list),
        sa.Column("prohibited_actions", sa.JSON, default=list),
        sa.Column("source_audio_uri", sa.Text, nullable=True),
        sa.Column("transcript_id", sa.String, nullable=True),
        sa.Column("interviewee", sa.String, nullable=True),
        sa.Column("interviewer", sa.String, nullable=True),
        sa.Column("reviewer", UUID(as_uuid=True), nullable=True),
        sa.Column("related_sop_ids", sa.JSON, default=list),
        sa.Column("conflict_report", sa.JSON, default=list),
        sa.Column("version", sa.Integer, default=1),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("knowhow_cards")
    op.drop_table("mka_approval_requests")
    op.drop_table("approval_policies")
    op.drop_table("rule_sets")
    op.drop_table("form_instances")
    op.drop_table("form_definitions")
    op.drop_index("ix_tenant_term_category", table_name="tenant_term_dictionaries")
    op.drop_table("tenant_term_dictionaries")
    op.drop_table("interaction_sessions")
    op.drop_table("tenant_module_bindings")
    op.drop_table("job_modules")