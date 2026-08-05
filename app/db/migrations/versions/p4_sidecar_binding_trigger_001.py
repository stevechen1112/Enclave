"""tenants INSERT 自動配發 sidecar binding 的 DB 觸發器（ADR-013 嚴謹性強化）。

Revision ID: p4_sidecar_binding_trigger_001
Revises: p4_sidecar_binding_001

動機（code review 後實測發現）：應用層 crud_tenant.create 的 ensure_binding
只能涵蓋走該函式的建立路徑；測試 fixture、腳本、人工 SQL 等直接 INSERT
tenants 的路徑會產生無 binding 的孤兒租戶（隔離破口）。以 DB 觸發器把
「租戶存在 ⇒ binding 存在」不變量下沉到資料庫層，任何寫入路徑都適用。

觸發器建立的是空 binding（pack 欄位 NULL＝未啟用）；pack 歸屬 ID 的
provision 是獨立流程（Phase 2 的 pack 啟用 API）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "p4_sidecar_binding_trigger_001"
down_revision: Union[str, None] = "p4_sidecar_binding_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_FUNCTION = """
CREATE OR REPLACE FUNCTION trg_tenant_sidecar_binding() RETURNS trigger AS $$
BEGIN
    INSERT INTO tenant_sidecar_bindings (tenant_id) VALUES (NEW.id)
    ON CONFLICT (tenant_id) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""


def upgrade() -> None:
    op.execute(_FUNCTION)
    op.execute(
        """
        DROP TRIGGER IF EXISTS tenant_sidecar_binding_on_insert ON tenants;
        CREATE TRIGGER tenant_sidecar_binding_on_insert
        AFTER INSERT ON tenants
        FOR EACH ROW EXECUTE FUNCTION trg_tenant_sidecar_binding()
        """
    )
    # 補齊觸發器建立前已存在的孤兒租戶（空 binding；歸屬 ID 由部署補種流程處理）
    op.execute(
        """
        INSERT INTO tenant_sidecar_bindings (tenant_id)
        SELECT t.id FROM tenants t
        LEFT JOIN tenant_sidecar_bindings b ON b.tenant_id = t.id
        WHERE b.tenant_id IS NULL
        ON CONFLICT (tenant_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS tenant_sidecar_binding_on_insert ON tenants"
    )
    op.execute("DROP FUNCTION IF EXISTS trg_tenant_sidecar_binding")
