"""Phase 6 — Agent tool approval persistence."""
import uuid
from sqlalchemy import Column, String, DateTime, ForeignKey, func, Text, JSON
from sqlalchemy.dialects.postgresql import UUID
from app.db.base_class import Base


class AgentApprovalRequest(Base):
    __tablename__ = "agent_approval_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    actor_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    tool_name = Column(String, nullable=False)
    tool_risk = Column(String, nullable=False)
    tool_category = Column(String, nullable=True)
    action_summary = Column(Text, nullable=False)
    target_system = Column(String, nullable=True)
    impact_scope = Column(Text, nullable=True)
    tool_args_json = Column(JSON, default=dict)
    policy_snapshot = Column(JSON, default=dict)
    status = Column(String, default="pending")  # pending | approved | rejected | expired
    approved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    reason = Column(Text, nullable=True)
    execution_result = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
