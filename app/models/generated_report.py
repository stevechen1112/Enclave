"""
Phase 11-2 — 生成報告持久化 Model

GeneratedReport: 儲存使用者透過「內容生成」功能產生的完整報告。
支援標題、模板類型、原始 prompt、完整內容、來源引用、收藏等。
"""

import uuid
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, func, Text, JSON, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base_class import Base


class GeneratedReport(Base):
    """使用者生成的報告（伺服器端持久化）。"""

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)

    # 報告內容
    title = Column(String(255), nullable=False, default="未命名報告")
    template = Column(String(50), nullable=False, index=True)  # draft_response, case_summary, ...
    prompt = Column(Text, nullable=False)
    context_query = Column(Text, nullable=True)
    content = Column(Text, nullable=False)
    word_count = Column(Integer, nullable=True)

    # 來源引用 — JSON array of {filename, score, chunk_text}
    sources = Column(JSON, nullable=True, default=list)

    # 使用的文件 IDs（跨案件生成時）
    document_ids = Column(JSON, nullable=True, default=list)

    # 使用者操作
    is_pinned = Column(Boolean, default=False, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    creator = relationship("User", foreign_keys=[created_by])
