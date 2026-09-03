"""Activate FORCE RLS for every canonical tenant isolation policy.

Revision ID: tenant_force_rls_pra_002
Revises: tenant_policy_reconcile_pra_001

The operation is intentionally driven by ``RLS_ENFORCEMENT_ENABLED`` so a
deployment can migrate in shadow mode.  The companion activation command is
idempotent and can enforce the same state after a shadow migration.
"""

from __future__ import annotations

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "tenant_force_rls_pra_002"
down_revision: str | None = "tenant_policy_reconcile_pra_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tenant_policy_tables() -> list[str]:
    rows = op.get_bind().execute(
        sa.text(
            """
            SELECT DISTINCT tablename
            FROM pg_catalog.pg_policies
            WHERE schemaname = 'public' AND policyname = 'tenant_isolation'
            ORDER BY tablename
            """
        )
    )
    return [str(row[0]) for row in rows]


def upgrade() -> None:
    if os.environ.get("RLS_ENFORCEMENT_ENABLED", "false").lower() != "true":
        return
    tables = _tenant_policy_tables()
    if not tables:
        raise RuntimeError("no tenant_isolation policies found for FORCE activation")
    for table in tables:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')


def downgrade() -> None:
    for table in _tenant_policy_tables():
        op.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
