"""
Phase 10 — 監控資料夾設定 Model

儲存使用者設定的監控資料夾清單，支援：
  - 多資料夾設定
  - 各資料夾獨立的額外設定（遞迴掃描、子資料夾深度限制、副檔名白名單）
  - 啟用/停用個別資料夾而不刪除設定
"""

import uuid
from sqlalchemy import Column, String, Boolean, DateTime, Integer, Text, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base_class import Base


class WatchFolder(Base):
    __tablename__ = "watch_folders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)

    # 資料夾設定
    folder_path = Column(Text, nullable=False)                  # 本機絕對路徑
    display_name = Column(String(255), nullable=True)           # 顯示名稱（選填）
    is_active = Column(Boolean, default=True, nullable=False)   # 是否啟用監控
    recursive = Column(Boolean, default=True, nullable=False)   # 是否掃描子資料夾
    max_depth = Column(Integer, default=10, nullable=False)     # 子資料夾最大深度

    # 設定
    allowed_extensions = Column(Text, nullable=True)            # JSON 陣列，None = 全部支援格式
    default_category = Column(String(255), nullable=True)       # 此資料夾文件的預設分類

    # 統計
    last_scan_at = Column(DateTime(timezone=True), nullable=True)
    total_files_watched = Column(Integer, default=0)

    # 時間戳
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    tenant = relationship("Tenant", backref="watch_folders")
    review_items = relationship("ReviewItem", backref="watch_folder", cascade="all, delete-orphan")
