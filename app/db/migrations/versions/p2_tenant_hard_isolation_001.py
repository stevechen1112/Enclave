"""Complete tenant RLS coverage for direct, identity, and inherited tables.

Revision ID: p2_tenant_hard_isolation_001
Revises: knowledge_authority_h1_012

Every table with a tenant_id column receives a policy.  Nullable tenant_id tables
use global-read/tenant-write semantics: shared templates may be read by tenants,
but only a maintenance bypass may create or mutate global rows.  Tables whose
tenant ownership is inherited through a parent foreign key receive explicit
EXISTS policies.  The tenants identity table is scoped by its id column.
"""

from __future__ import annotations

import os
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "p2_tenant_hard_isolation_001"
down_revision: str | None = "knowledge_authority_h1_012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUC = "app.tenant_id"
_BYPASS_GUC = "app.bypass_rls"
_BYPASS_ROLE = "enclave_rls_bypass"
_APPLICATION_ROLE = "enclave_application"
_BYPASS_EXPR = (
    f"(current_setting('{_BYPASS_GUC}', true) = 'on' "
    f"AND pg_has_role(current_user, '{_BYPASS_ROLE}', 'member'))"
)

_NULLABLE_GLOBAL_READ_TABLES = {
    "approval_policies",
    "form_definitions",
    "integrityreports",
    "job_modules",
    "kbbackups",
    "knowledge_evaluation_runs",
    "mka_task_definitions",
    "rule_sets",
}

_INHERITED_POLICIES = {
    "document_artifacts": (
        "EXISTS (SELECT 1 FROM documents p WHERE p.id = document_id "
        f"AND p.tenant_id = NULLIF(current_setting('{_TENANT_GUC}', true), '')::uuid)"
    ),
    "knowledge_base_members": (
        "EXISTS (SELECT 1 FROM knowledge_bases p WHERE p.id = kb_id "
        f"AND p.tenant_id = NULLIF(current_setting('{_TENANT_GUC}', true), '')::uuid)"
    ),
    "knowledge_base_revisions": (
        "EXISTS (SELECT 1 FROM knowledge_bases p WHERE p.id = kb_id "
        f"AND p.tenant_id = NULLIF(current_setting('{_TENANT_GUC}', true), '')::uuid)"
    ),
    "knowledge_evaluation_case_results": (
        "EXISTS (SELECT 1 FROM knowledge_evaluation_runs p WHERE p.id = run_id "
        f"AND p.tenant_id = NULLIF(current_setting('{_TENANT_GUC}', true), '')::uuid)"
    ),
    "knowledge_evaluation_human_reviews": (
        "EXISTS (SELECT 1 FROM knowledge_evaluation_case_results c "
        "JOIN knowledge_evaluation_runs p ON p.id = c.run_id "
        "WHERE c.id = case_result_id "
        f"AND p.tenant_id = NULLIF(current_setting('{_TENANT_GUC}', true), '')::uuid)"
    ),
    "messages": (
        "EXISTS (SELECT 1 FROM conversations p WHERE p.id = conversation_id "
        f"AND p.tenant_id = NULLIF(current_setting('{_TENANT_GUC}', true), '')::uuid)"
    ),
    "wiki_revisions": (
        "EXISTS (SELECT 1 FROM wiki_pages p WHERE p.id = wiki_page_id "
        f"AND p.tenant_id = NULLIF(current_setting('{_TENANT_GUC}', true), '')::uuid)"
    ),
}


def _direct_policy(*, nullable: bool) -> str:
    global_read = "tenant_id IS NULL OR " if nullable else ""
    return f"""
CREATE POLICY tenant_isolation ON "{{table}}"
  USING (
    {global_read}tenant_id = NULLIF(current_setting('{_TENANT_GUC}', true), '')::uuid
    OR {_BYPASS_EXPR}
  )
  WITH CHECK (
    tenant_id = NULLIF(current_setting('{_TENANT_GUC}', true), '')::uuid
    OR {_BYPASS_EXPR}
  )
"""


def _enable(table: str, policy: str, *, force: bool) -> None:
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
    op.execute(policy)
    mode = "FORCE" if force else "NO FORCE"
    op.execute(f'ALTER TABLE "{table}" {mode} ROW LEVEL SECURITY')


def _tenant_columns(bind) -> list[tuple[str, bool]]:
    rows = bind.execute(
        sa.text(
            """
            SELECT table_name, is_nullable = 'YES' AS nullable
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND column_name = 'tenant_id'
              AND table_name <> 'tenants'
            ORDER BY table_name
            """
        )
    ).fetchall()
    return [(str(row[0]), bool(row[1])) for row in rows]


def upgrade() -> None:
    bind = op.get_bind()
    force = os.environ.get("RLS_ENFORCEMENT_ENABLED", "false").lower() == "true"

    # Legacy control-plane projections carried tenant ownership only in JSON or
    # indirectly through resource IDs.  Materialise it before policy discovery;
    # ambiguous historical rows deliberately block the migration instead of
    # becoming globally visible.
    for table in (
        "outbox_events",
        "projection_status",
        "sync_cursors",
        "dead_letter_events",
        "gateway_resources",
    ):
        op.add_column(table, sa.Column("tenant_id", sa.UUID(), nullable=True))

    op.execute(
        r"""
UPDATE outbox_events e
SET tenant_id = CASE
  WHEN coalesce(e.payload->>'tenant_id', '') ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    THEN (e.payload->>'tenant_id')::uuid
  WHEN e.aggregate_type = 'tenant' AND e.aggregate_id ~* '^[0-9a-f-]{36}$'
    THEN e.aggregate_id::uuid
  ELSE NULL
END
"""
    )
    op.execute(
        """
UPDATE outbox_events e SET tenant_id = d.tenant_id
FROM documents d
WHERE e.tenant_id IS NULL AND e.aggregate_type = 'document'
  AND e.aggregate_id = d.id::text;
UPDATE outbox_events e SET tenant_id = w.tenant_id
FROM wiki_pages w
WHERE e.tenant_id IS NULL AND e.aggregate_type = 'wiki'
  AND e.aggregate_id = w.id::text;
UPDATE outbox_events e SET tenant_id = c.tenant_id
FROM connector_instances c
WHERE e.tenant_id IS NULL AND e.aggregate_type = 'connector'
  AND e.aggregate_id = c.id::text;
UPDATE outbox_events e SET tenant_id = k.tenant_id
FROM knowledge_bases k
WHERE e.tenant_id IS NULL AND e.aggregate_type = 'kb'
  AND e.aggregate_id = k.id::text
"""
    )
    for table in ("projection_status", "gateway_resources"):
        op.execute(
            f"""
UPDATE {table} r SET tenant_id = d.tenant_id
FROM documents d
WHERE r.tenant_id IS NULL AND r.enclave_resource_type = 'document'
  AND r.enclave_resource_id = d.id::text
"""
            if table == "gateway_resources"
            else f"""
UPDATE {table} r SET tenant_id = d.tenant_id
FROM documents d
WHERE r.tenant_id IS NULL AND r.resource_type = 'document'
  AND r.resource_id = d.id::text
"""
        )
        resource_type_column = (
            "enclave_resource_type" if table == "gateway_resources" else "resource_type"
        )
        resource_id_column = (
            "enclave_resource_id" if table == "gateway_resources" else "resource_id"
        )
        for resource_type, source_table in (
            ("chunk", "documentchunks"),
            ("wiki", "wiki_pages"),
            ("wiki_page", "wiki_pages"),
            ("graph_entity", "graph_entities"),
        ):
            op.execute(
                f"""
UPDATE {table} r SET tenant_id = s.tenant_id
FROM {source_table} s
WHERE r.tenant_id IS NULL
  AND r.{resource_type_column} = '{resource_type}'
  AND r.{resource_id_column} = s.id::text
"""
            )
    op.execute(
        """
UPDATE sync_cursors s SET tenant_id = c.tenant_id
FROM connector_instances c
WHERE s.connector_instance_id = c.id::text;
UPDATE dead_letter_events d SET tenant_id = e.tenant_id
FROM outbox_events e
WHERE d.original_event_id = e.id
"""
    )
    for table in (
        "outbox_events",
        "projection_status",
        "sync_cursors",
        "dead_letter_events",
        "gateway_resources",
    ):
        unresolved = bind.execute(
            sa.text(f'SELECT count(*) FROM "{table}" WHERE tenant_id IS NULL')
        ).scalar_one()
        if unresolved:
            raise RuntimeError(
                f"{table} has {unresolved} rows with ambiguous tenant ownership"
            )
        op.alter_column(table, "tenant_id", nullable=False)
        op.create_foreign_key(
            f"fk_{table}_tenant_id",
            table,
            "tenants",
            ["tenant_id"],
            ["id"],
        )
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])

    # Idempotency and projection identity are tenant-local invariants. Keeping
    # their legacy global uniqueness would let another tenant cause collisions
    # even though RLS correctly hides the conflicting row.
    op.drop_constraint("uq_outbox_idempotency", "outbox_events", type_="unique")
    op.create_unique_constraint(
        "uq_outbox_idempotency",
        "outbox_events",
        ["tenant_id", "idempotency_key"],
    )
    op.execute("DROP INDEX IF EXISTS uq_projection_status_resource_provider")
    op.execute(
        """
        CREATE UNIQUE INDEX uq_projection_status_resource_provider
        ON projection_status (
          tenant_id, resource_type, resource_id, provider, provider_instance_id
        ) NULLS NOT DISTINCT
        """
    )
    op.drop_constraint("uq_sync_cursor_instance", "sync_cursors", type_="unique")
    op.create_unique_constraint(
        "uq_sync_cursor_instance",
        "sync_cursors",
        ["tenant_id", "connector_instance_id"],
    )
    op.execute("DROP INDEX IF EXISTS uq_gateway_resource_mapping_nulls")
    op.execute(
        """
        CREATE UNIQUE INDEX uq_gateway_resource_mapping_nulls
        ON gateway_resources (
          tenant_id, enclave_resource_type, enclave_resource_id,
          provider, provider_instance_id
        ) NULLS NOT DISTINCT
        """
    )

    # Marker roles carry no database privilege by themselves.  Policies require
    # membership in the bypass marker in addition to the transaction GUC, so an
    # application connection cannot self-authorise by setting a custom GUC.
    op.execute(
        f"""
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{_BYPASS_ROLE}') THEN
    CREATE ROLE {_BYPASS_ROLE}
      NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{_APPLICATION_ROLE}') THEN
    CREATE ROLE {_APPLICATION_ROLE}
      NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
  END IF;
END
$$
"""
    )

    op.create_table(
        "platform_maintenance_audit",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "db_role", sa.Text(), server_default=sa.text("current_user"), nullable=False
        ),
        sa.Column("actor_identity", sa.Text(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("correlation_id", sa.Text(), nullable=True),
        sa.Column(
            "metadata_json",
            sa.JSON(),
            server_default=sa.text("'{}'::json"),
            nullable=False,
        ),
    )
    op.execute("REVOKE ALL ON TABLE platform_maintenance_audit FROM PUBLIC")
    op.execute(f"GRANT INSERT ON TABLE platform_maintenance_audit TO {_BYPASS_ROLE}")
    op.execute(
        f"GRANT USAGE, SELECT ON SEQUENCE platform_maintenance_audit_id_seq TO {_BYPASS_ROLE}"
    )

    # Password login needs to resolve an e-mail to a tenant before RLS context
    # exists.  Expose only tenant_id through a fixed SECURITY DEFINER function;
    # password hashes and cross-tenant rows never become visible to the app role.
    op.execute(
        """
CREATE OR REPLACE FUNCTION public.enclave_resolve_login_tenant(login_email text)
RETURNS uuid
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
  SELECT u.tenant_id
  FROM public.users AS u
  WHERE lower(u.email) = lower(login_email)
  LIMIT 1
$$
"""
    )
    op.execute(
        "REVOKE ALL ON FUNCTION public.enclave_resolve_login_tenant(text) FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION public.enclave_resolve_login_tenant(text) TO {_APPLICATION_ROLE}"
    )

    _enable(
        "tenants",
        f"""
CREATE POLICY tenant_isolation ON tenants
  USING (
    id = NULLIF(current_setting('{_TENANT_GUC}', true), '')::uuid
    OR {_BYPASS_EXPR}
  )
  WITH CHECK (
    id = NULLIF(current_setting('{_TENANT_GUC}', true), '')::uuid
    OR {_BYPASS_EXPR}
  )
""",
        force=force,
    )

    for table, nullable in _tenant_columns(bind):
        if nullable and table not in _NULLABLE_GLOBAL_READ_TABLES:
            raise RuntimeError(
                f"Nullable tenant table {table!r} lacks an explicit global-read decision"
            )
        _enable(
            table,
            _direct_policy(nullable=nullable).format(table=table),
            force=force,
        )

    for table, tenant_predicate in _INHERITED_POLICIES.items():
        _enable(
            table,
            f"""
CREATE POLICY tenant_isolation ON "{table}"
  USING (({tenant_predicate}) OR {_BYPASS_EXPR})
  WITH CHECK (({tenant_predicate}) OR {_BYPASS_EXPR})
""",
            force=force,
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = [
        "tenants",
        *[table for table, _ in _tenant_columns(bind)],
        *_INHERITED_POLICIES,
    ]
    for table in dict.fromkeys(tables):
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
        op.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
    op.execute("DROP FUNCTION IF EXISTS public.enclave_resolve_login_tenant(text)")
    op.execute("DROP TABLE IF EXISTS platform_maintenance_audit")
    op.drop_constraint("uq_outbox_idempotency", "outbox_events", type_="unique")
    op.create_unique_constraint(
        "uq_outbox_idempotency", "outbox_events", ["idempotency_key"]
    )
    op.execute("DROP INDEX IF EXISTS uq_projection_status_resource_provider")
    op.execute(
        """
        CREATE UNIQUE INDEX uq_projection_status_resource_provider
        ON projection_status (
          resource_type, resource_id, provider, provider_instance_id
        ) NULLS NOT DISTINCT
        """
    )
    op.drop_constraint("uq_sync_cursor_instance", "sync_cursors", type_="unique")
    op.create_unique_constraint(
        "uq_sync_cursor_instance", "sync_cursors", ["connector_instance_id"]
    )
    op.execute("DROP INDEX IF EXISTS uq_gateway_resource_mapping_nulls")
    op.execute(
        """
        CREATE UNIQUE INDEX uq_gateway_resource_mapping_nulls
        ON gateway_resources (
          enclave_resource_type, enclave_resource_id,
          provider, provider_instance_id
        ) NULLS NOT DISTINCT
        """
    )
    for table in (
        "gateway_resources",
        "dead_letter_events",
        "sync_cursors",
        "projection_status",
        "outbox_events",
    ):
        op.drop_index(f"ix_{table}_tenant_id", table_name=table)
        op.drop_constraint(
            f"fk_{table}_tenant_id", table_name=table, type_="foreignkey"
        )
        op.drop_column(table, "tenant_id")
