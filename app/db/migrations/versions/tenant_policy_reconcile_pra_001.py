"""Reconcile post-P2 tenant policies with the audited bypass contract.

Revision ID: tenant_policy_reconcile_pra_001
Revises: knowledge_typed_relation_kq4_001

Several tables added after the P2 hard-isolation migration inherited the old
``app.bypass_rls=on``-only predicate.  An ordinary database login can set a
custom PostgreSQL GUC, so the bypass must also require membership in the
NOLOGIN ``enclave_rls_bypass`` marker role.
"""

from __future__ import annotations

import os
from collections.abc import Sequence

from alembic import op

revision: str = "tenant_policy_reconcile_pra_001"
down_revision: str | None = "knowledge_typed_relation_kq4_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = (
    "import_batch_items",
    "import_batches",
    "input_operation_metrics",
    "input_pilot_acceptances",
    "input_pilot_audits",
    "input_pilot_daily_metrics",
    "input_pilot_incidents",
    "input_pilots",
    "knowledge_unit_relation_projections",
    "upload_parts",
    "upload_sessions",
)

_TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
_LEGACY_BYPASS = "current_setting('app.bypass_rls', true) = 'on'"
_AUDITED_BYPASS = (
    f"({_LEGACY_BYPASS} "
    "AND pg_has_role(current_user, 'enclave_rls_bypass', 'member'))"
)


def _replace_policy(table: str, *, bypass: str) -> None:
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
    op.execute(
        f'''CREATE POLICY tenant_isolation ON "{table}"
        USING (tenant_id = {_TENANT} OR {bypass})
        WITH CHECK (tenant_id = {_TENANT} OR {bypass})'''
    )


def upgrade() -> None:
    for table in _TABLES:
        _replace_policy(table, bypass=_AUDITED_BYPASS)
        if os.environ.get("RLS_ENFORCEMENT_ENABLED", "false").lower() == "true":
            op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')


def downgrade() -> None:
    # Restore the exact predicate installed by each table's originating
    # migration.  Do not alter FORCE state during a policy-only rollback.
    for table in _TABLES:
        _replace_policy(table, bypass=_LEGACY_BYPASS)
