"""補 RLS policy 給 p5/p6 後建表（tenant_sso_configs、billing_records）。

Revision ID: p7_rls_new_tables_001
Revises: p6_billing_001
"""
import os
from typing import Sequence, Union

from alembic import op

revision: str = "p7_rls_new_tables_001"
down_revision: Union[str, None] = "p6_billing_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ("tenant_sso_configs", "billing_records")

_POLICY = """
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


def upgrade() -> None:
    force = os.environ.get("RLS_ENFORCEMENT_ENABLED", "false").lower() == "true"
    for table in _TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
        op.execute(_POLICY.format(table=table))
        if force:
            op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        else:
            op.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
