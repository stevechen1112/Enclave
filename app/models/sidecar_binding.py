"""Tenant-sidecar 歸屬綁定（ADR-013）：sidecar 資源歸屬的唯一權威。

每個租戶一列；各 sidecar 的 dataset／KB／org ID 記在這裡，
運行期禁止再從全域環境變數決定租戶歸屬（環境變數僅供 migration 種子
與 adapter 層的部署級預設）。NULL 表示該 pack 未為此租戶啟用。
"""
from sqlalchemy import Column, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID

from app.db.base_class import Base


class TenantSidecarBinding(Base):
    __tablename__ = "tenant_sidecar_bindings"

    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), primary_key=True
    )
    ragflow_dataset_id = Column(String, nullable=True)
    weknora_kb_id = Column(String, nullable=True)
    pipeshub_org_id = Column(String, nullable=True)
    credentials_ref = Column(String, nullable=True)  # credential_vault 參照
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
