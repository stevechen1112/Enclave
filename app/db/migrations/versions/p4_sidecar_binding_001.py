"""tenant_sidecar_bindings 表＋現有租戶種子（ADR-013）。

Revision ID: p4_sidecar_binding_001
Revises: rls_tenant_isolation_001

種子規則：對每個現有租戶建立 binding，值取自部署級環境變數
（RAGFLOW_DATASET_ID／WEKNORA_KB_ID，WEKNORA_DEFAULT_KB_ID 為次順位）——
這是全域環境變數唯一合法的歸屬用途；種子後運行期歸屬以本表為準。
"""
import os
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "p4_sidecar_binding_001"
down_revision: Union[str, None] = "rls_tenant_isolation_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "tenant_sidecar_bindings" not in inspector.get_table_names():
        op.create_table(
            "tenant_sidecar_bindings",
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), primary_key=True),
            sa.Column("ragflow_dataset_id", sa.String(), nullable=True),
            sa.Column("weknora_kb_id", sa.String(), nullable=True),
            sa.Column("pipeshub_org_id", sa.String(), nullable=True),
            sa.Column("credentials_ref", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    # 種子：現有租戶 ← 部署級環境變數（單租戶部署下所有租戶共享同一 sidecar 歸屬）。
    # 注意：alembic 在容器外執行時 env 未必已載入，故 fallback 解析 repo 根目錄
    # 的 .env；兩者皆無則種子為 NULL，需以補種腳本回填（見 ADR-013 後果）。
    def _env(name: str):
        val = (os.getenv(name) or "").strip()
        if val:
            return val
        env_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "..", ".env"
        )
        try:
            with open(env_path, encoding="utf-8") as f:
                for line in f:
                    if line.startswith(f"{name}="):
                        return line.split("=", 1)[1].strip() or None
        except OSError:
            pass
        return None

    dataset_id = _env("RAGFLOW_DATASET_ID")
    kb_id = _env("WEKNORA_KB_ID") or _env("WEKNORA_DEFAULT_KB_ID")
    tenants = bind.execute(sa.text("SELECT id FROM tenants")).fetchall()
    for (tid,) in tenants:
        bind.execute(
            sa.text(
                """
                INSERT INTO tenant_sidecar_bindings
                    (tenant_id, ragflow_dataset_id, weknora_kb_id)
                VALUES (:tid, :ds, :kb)
                ON CONFLICT (tenant_id) DO NOTHING
                """
            ),
            {"tid": tid, "ds": dataset_id, "kb": kb_id},
        )


def downgrade() -> None:
    op.drop_table("tenant_sidecar_bindings")
