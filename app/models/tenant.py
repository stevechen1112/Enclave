import uuid
from sqlalchemy import Column, String, Boolean, DateTime, Integer, Float, Enum, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base_class import Base

class Tenant(Base):
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    name = Column(String, index=True, nullable=False)
    plan = Column(String, default="free")  # free, pro, enterprise
    status = Column(String, default="active")  # active, suspended
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # ── Quota 配額欄位 ──
    max_users = Column(Integer, nullable=True, default=None)            # null = 無限制
    max_documents = Column(Integer, nullable=True, default=None)
    max_storage_mb = Column(Integer, nullable=True, default=None)
    monthly_query_limit = Column(Integer, nullable=True, default=None)  # 每月查詢次數上限
    monthly_token_limit = Column(Integer, nullable=True, default=None)  # 每月 token 上限
    quota_alert_threshold = Column(Float, default=0.8)                  # 配額告警閾值 (0~1)
    quota_alert_email = Column(String, nullable=True)                   # 告警通知信箱

    # ── Security Config 安全組態欄位 ──
    isolation_level = Column(String, default="standard")                # standard | enhanced | strict
    require_mfa = Column(Boolean, default=False)
    ip_whitelist = Column(Text, nullable=True)                          # 逗號分隔的 IP/CIDR 清單

    # Relationships
    users = relationship("User", back_populates="tenant")
    documents = relationship("Document", back_populates="tenant")
    conversations = relationship("Conversation", back_populates="tenant")
    audit_logs = relationship("AuditLog", back_populates="tenant")
    usage_records = relationship("UsageRecord", back_populates="tenant")
    departments = relationship("Department", back_populates="tenant")
    feature_permissions = relationship("FeaturePermission", back_populates="tenant")
