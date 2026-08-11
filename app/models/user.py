import uuid
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import enum
from app.db.base_class import Base

class UserRole(str, enum.Enum):
    OWNER = "owner"
    ADMIN = "admin"
    HR = "hr"
    EMPLOYEE = "employee"
    VIEWER = "viewer"

class User(Base):
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String, nullable=True)
    hashed_password = Column(String, nullable=False)
    status = Column(String, default="active")
    role = Column(String, default="employee")
    is_superuser = Column(Boolean, default=False)

    # CG-AUTH-SSO：email 驗證與 TOTP MFA
    email_verified = Column(Boolean, default=False, nullable=False, server_default="false")
    mfa_enabled = Column(Boolean, default=False, nullable=False, server_default="false")
    mfa_secret = Column(String, nullable=True)

    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    department_id = Column(UUID(as_uuid=True), ForeignKey("departments.id"), nullable=True, index=True)
    # MKA：多職能使用者的 active 職能（持久化；NULL = 未選擇，fallback 到 primary 指派）
    active_job_role_id = Column(UUID(as_uuid=True), ForeignKey("mka_job_roles.id"), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    tenant = relationship("Tenant", back_populates="users")
    department = relationship("Department", back_populates="users")

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    conversations = relationship("Conversation", back_populates="user")
    usage_records = relationship("UsageRecord", back_populates="user")
