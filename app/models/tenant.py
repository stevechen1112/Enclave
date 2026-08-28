import uuid
from sqlalchemy import CheckConstraint, Column, String, Boolean, DateTime, Integer, Float, Enum, Text, func, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base_class import Base

class Tenant(Base):
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    name = Column(String, index=True, nullable=False)
    plan = Column(String, default="free")  # free, pro, enterprise
    status = Column(String, default="active")  # active, suspended
    is_demo = Column(
        Boolean, nullable=False, default=False, server_default="false", index=True
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # ── Quota 配額欄位 ──
    max_users = Column(Integer, nullable=True, default=None)            # null = 無限制
    max_documents = Column(Integer, nullable=True, default=None)
    max_storage_mb = Column(Integer, nullable=True, default=None)
    monthly_query_limit = Column(Integer, nullable=True, default=None)  # 每月查詢次數上限
    monthly_token_limit = Column(Integer, nullable=True, default=None)  # 每月 token 上限
    monthly_cost_limit_usd = Column(Float, nullable=True, default=None)
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
    sso_configs = relationship("TenantSSOConfig", back_populates="tenant")

    __table_args__ = (
        CheckConstraint(
            "monthly_cost_limit_usd IS NULL OR monthly_cost_limit_usd >= 0",
            name="ck_tenants_monthly_cost_limit_nonnegative",
        ),
    )


class TenantSSOConfig(Base):
    """租戶級 SSO 設定（CG-AUTH-SSO）。

    注意：auto_create_user 預設 False（fail-closed）——Sales-Led 受控開戶下，
    SSO 登入只連結既有帳號，不自動開通新用戶，避免陌生人網域撞入。
    """

    __tablename__ = "tenant_sso_configs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    provider = Column(String, nullable=False)  # google | microsoft
    client_id = Column(String, nullable=False)
    client_secret = Column(String, nullable=False)
    redirect_uri = Column(String, nullable=True)
    enabled = Column(Boolean, default=True, nullable=False, server_default="true")
    allowed_domains = Column(JSON, default=list)
    auto_create_user = Column(Boolean, default=False, nullable=False, server_default="false")
    default_role = Column(String, default="employee")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    tenant = relationship("Tenant", back_populates="sso_configs")
