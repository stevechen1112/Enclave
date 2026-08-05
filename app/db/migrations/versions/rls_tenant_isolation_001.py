"""PostgreSQL Row-Level Security 租戶隔離（ADR-012）。

Revision ID: rls_tenant_isolation_001
Revises: f2_documents_genre_001

行為：
- 對所有「含 NOT NULL tenant_id」的 public 表啟用 RLS 並建立 tenant_isolation policy
  （tenants 表本身除外；nullable tenant_id 的系統表如 kbbackups／integrityreports
  不在自動範圍，需逐表決策後另行處理——見 ADR-012）。
- 預設**不** FORCE：表 owner（應用連線角色）不受約束 → shadow 階段行為不變。
- 部署時以環境變數 ``RLS_ENFORCEMENT_ENABLED=true`` 執行 ``alembic upgrade head``
  才會 ``FORCE ROW LEVEL SECURITY``（連 owner 也受約束）→ enforce 階段。
- policy 內建 fail-closed：未設 ``app.tenant_id`` 時比對 NULL 不成立，查無列；
  ``app.bypass_rls=on`` 為平台維運通道（見 app/services/rls.py 的用途限制）。

部署前提（ADR-012 硬性要求）：enforce 階段應用程式 DB 角色必須是非
superuser、無 BYPASSRLS 屬性的專用帳號——superuser 天生跳過 RLS，
FORCE 也無效（tests/test_rls.py live 攻擊測試實證）。
"""
import os
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "rls_tenant_isolation_001"
down_revision: Union[str, None] = "f2_documents_genre_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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


def _tenant_tables(bind) -> list[str]:
    """動態發現含 NOT NULL tenant_id 的表（tenants 本身除外）。"""
    rows = bind.execute(
        sa.text(
            """
            SELECT table_name FROM information_schema.columns
            WHERE table_schema = 'public'
              AND column_name = 'tenant_id'
              AND is_nullable = 'NO'
            ORDER BY table_name
            """
        )
    ).fetchall()
    return [r[0] for r in rows if r[0] != "tenants"]


def upgrade() -> None:
    bind = op.get_bind()
    force = os.environ.get("RLS_ENFORCEMENT_ENABLED", "false").lower() == "true"

    for table in _tenant_tables(bind):
        # 表名來自 information_schema（非使用者輸入）
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
        op.execute(_POLICY.format(table=table))
        if force:
            op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        else:
            # 重跑本 migration 且未開 enforce → 確保回到 shadow 狀態
            op.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')


def downgrade() -> None:
    bind = op.get_bind()
    for table in _tenant_tables(bind):
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
        op.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
