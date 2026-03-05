"""
Phase 10 — 審核佇列項目 Model

每個被 Agent 發現的檔案，在人工確認前存為一條 ReviewItem 記錄。

狀態機：
  pending → approved / modified / rejected
  approved / modified → processing → indexed
  processing → failed（錯誤時回退）
"""

import uuid
from sqlalchemy import Column, String, Boolean, DateTime, Float, Text, Integer, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.db.base_class import Base


class ReviewItem(Base):
    __tablename__ = "review_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)

    # 原始檔案資訊
    file_path = Column(Text, nullable=False)
    file_name = Column(String(512), nullable=False)
    file_size = Column(Integer, nullable=True)
    file_ext = Column(String(20), nullable=True)
    watch_folder_id = Column(UUID(as_uuid=True), ForeignKey("watch_folders.id"), nullable=True)

    # AI 分類提案
    suggested_category = Column(String(255), nullable=True)
    suggested_subcategory = Column(String(255), nullable=True)
    suggested_tags = Column(JSONB, nullable=True)       # {"date": "2023-04", "person": "王小明", ...}
    confidence_score = Column(Float, nullable=True)     # 0.0 ~ 1.0
    reasoning = Column(Text, nullable=True)             # AI 判斷依據說明

    # 人工審核結果
    status = Column(String(50), default="pending", nullable=False, index=True)
    approved_category = Column(String(255), nullable=True)      # 人工修改後的分類
    approved_tags = Column(JSONB, nullable=True)                # 人工修改後的標籤
    reviewer_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    review_note = Column(Text, nullable=True)                   # 審核備註
    reviewed_at = Column(DateTime(timezone=True), nullable=True)

    # 向量化結果
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=True)
    indexed_at = Column(DateTime(timezone=True), nullable=True)
    indexing_error = Column(Text, nullable=True)

    # 時間戳
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    tenant = relationship("Tenant")
    reviewer = relationship("User", foreign_keys=[reviewer_id])
    document = relationship("Document")
