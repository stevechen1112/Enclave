"""MKA vision platform: scene registry, job roles, templates, writes, metrics.

對照願景補齊計畫 §1–§6：SceneRegistry migration、職能指派、公司版型、
寫入護欄持久化、MKA 事件指標。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSON

revision: str = "mka_p2_vision_platform_001"
down_revision: Union[str, None] = "mka_p1_audio_retention_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TENANT_TABLES = (
    "mka_scene_registry",
    "mka_job_roles",
    "mka_user_job_role_assignments",
    "mka_form_templates",
    "mka_write_requests",
    "mka_write_audits",
    "mka_events",
    "mka_knowhow_lineage",
    "mka_review_reminders",
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


def _enable_rls(table: str) -> None:
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
    op.execute(_TENANT_POLICY.format(table=table))
    op.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')


def upgrade() -> None:
    op.create_table(
        "mka_scene_registry",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("token", sa.String(), nullable=False, index=True),
        sa.Column("site_id", sa.String(), nullable=True),
        sa.Column("plant_id", sa.String(), nullable=True),
        sa.Column("line_id", sa.String(), nullable=True),
        sa.Column("equipment_id", sa.String(), nullable=True),
        sa.Column("equipment_model", sa.String(), nullable=True),
        sa.Column("work_order_id", sa.String(), nullable=True),
        sa.Column("product_id", sa.String(), nullable=True),
        sa.Column("part_number", sa.String(), nullable=True),
        sa.Column("customer_id", sa.String(), nullable=True),
        sa.Column("document_version_scope", sa.String(), nullable=True),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "token", name="uq_mka_scene_registry_tenant_token"),
    )

    op.create_table(
        "mka_job_roles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("role_key", sa.String(), nullable=False, index=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("department_ids", JSON(), server_default="[]"),
        sa.Column("default_module_keys", JSON(), server_default="[]"),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "role_key", name="uq_mka_job_role_tenant_key"),
    )

    op.create_table(
        "mka_user_job_role_assignments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("job_role_id", UUID(as_uuid=True), sa.ForeignKey("mka_job_roles.id"), nullable=False, index=True),
        sa.Column("department_id", UUID(as_uuid=True), nullable=True),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "user_id", "job_role_id", name="uq_mka_user_job_role"),
    )

    op.create_table(
        "mka_form_templates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("form_key", sa.String(), nullable=False, index=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("format", sa.String(), nullable=False),  # docx | xlsx
        sa.Column("version", sa.String(), server_default="1.0", nullable=False),
        sa.Column("storage_key", sa.String(), nullable=False),
        sa.Column("placeholders", JSON(), server_default="[]"),
        sa.Column("field_mapping", JSON(), server_default="{}"),
        sa.Column("status", sa.String(), server_default="draft", nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("supersedes_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "form_key", "version", name="uq_mka_form_template_version"),
    )

    op.create_table(
        "mka_write_requests",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("request_id", sa.String(), nullable=False, index=True),
        sa.Column("correlation_id", sa.String(), nullable=False, index=True),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("target_system", sa.String(), nullable=False),
        sa.Column("operation", sa.String(), nullable=False),
        sa.Column("risk", sa.String(), nullable=False),
        sa.Column("payload", JSON(), server_default="{}"),
        sa.Column("payload_hash", sa.String(), nullable=False),
        sa.Column("approval_token", sa.String(), nullable=True),
        sa.Column("approval_required", sa.Boolean(), server_default=sa.true()),
        sa.Column("status", sa.String(), server_default="pending", nullable=False),
        sa.Column("result", JSON(), server_default="{}"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default="0"),
        sa.Column("max_retries", sa.Integer(), server_default="3"),
        sa.Column("initiated_by", UUID(as_uuid=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_mka_write_idempotency"),
        sa.UniqueConstraint("tenant_id", "request_id", name="uq_mka_write_request_id"),
    )

    op.create_table(
        "mka_write_audits",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("write_request_id", UUID(as_uuid=True), sa.ForeignKey("mka_write_requests.id"), nullable=True),
        sa.Column("correlation_id", sa.String(), nullable=False, index=True),
        sa.Column("request_id", sa.String(), nullable=False),
        sa.Column("event", sa.String(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("target_system", sa.String(), nullable=True),
        sa.Column("risk", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), index=True),
    )

    op.create_table(
        "mka_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("event_type", sa.String(), nullable=False, index=True),
        sa.Column("module_key", sa.String(), nullable=True, index=True),
        sa.Column("user_id", UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("object_type", sa.String(), nullable=True),
        sa.Column("object_id", sa.String(), nullable=True),
        sa.Column("metrics", JSON(), server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), index=True),
    )

    op.create_table(
        "mka_knowhow_lineage",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("card_id", UUID(as_uuid=True), sa.ForeignKey("knowhow_cards.id"), nullable=False, index=True),
        sa.Column("audio_uri", sa.String(), nullable=True),
        sa.Column("transcript_id", sa.String(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recorded_by", UUID(as_uuid=True), nullable=True),
        sa.Column("duration_seconds", sa.Float(), server_default="0"),
        sa.Column("retention_policy", sa.String(), server_default="transcript_only"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consent_obtained", sa.Boolean(), server_default=sa.false()),
        sa.Column("consent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consent_by", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "mka_review_reminders",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("card_id", UUID(as_uuid=True), sa.ForeignKey("knowhow_cards.id"), nullable=False, index=True),
        sa.Column("card_title", sa.String(), nullable=True),
        sa.Column("reviewer_id", UUID(as_uuid=True), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reminder_type", sa.String(), server_default="expiry"),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("sent", sa.Boolean(), server_default=sa.false()),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Expand FormDefinition for tenant schema / active template
    op.add_column("form_definitions", sa.Column("field_sources", JSON(), server_default="{}"))
    op.add_column("form_definitions", sa.Column("active_template_id", UUID(as_uuid=True), nullable=True))
    op.add_column("form_definitions", sa.Column("approval_policy_json", JSON(), server_default="{}"))

    for table in _TENANT_TABLES:
        _enable_rls(table)


def downgrade() -> None:
    op.drop_column("form_definitions", "approval_policy_json")
    op.drop_column("form_definitions", "active_template_id")
    op.drop_column("form_definitions", "field_sources")
    for table in reversed(_TENANT_TABLES):
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
        op.drop_table(table)
