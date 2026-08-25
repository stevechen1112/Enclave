import uuid

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from app.db.base_class import Base


class ChatFeedback(Base):
    """聊天回饋（T7-5）— 使用者對 AI 回答的評價"""
    __tablename__ = "chat_feedbacks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    message_id = Column(UUID(as_uuid=True), ForeignKey("messages.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    rating = Column(SmallInteger, nullable=False)  # 1=👎, 2=👍
    category = Column(String(50), nullable=True)  # wrong_answer / incomplete / outdated / hallucination / other
    comment = Column(Text, nullable=True)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    status = Column(String(24), nullable=False, default="open")
    processing_history = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 同一使用者對同一則訊息僅允許 1 筆回饋（可更新）
    __table_args__ = (
        UniqueConstraint("user_id", "message_id", name="uq_feedback_user_message"),
        Index("ix_chat_feedbacks_owner_id", "owner_id"),
    )
