"""Persistent deny-first policy entries (survive process restarts)."""
import uuid
from sqlalchemy import Column, String, DateTime, ForeignKey, func, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from app.db.base_class import Base


class PolicyDenyEntry(Base):
    __tablename__ = "policy_deny_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    resource_type = Column(String, nullable=False)
    resource_id = Column(String, nullable=False, index=True)
    subject_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    reason = Column(String, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("resource_type", "resource_id", "subject_id", name="uq_policy_deny"),
        Index("ix_policy_deny_resource", "resource_type", "resource_id"),
    )
