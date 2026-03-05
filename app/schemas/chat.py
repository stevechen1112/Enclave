from typing import Any, Dict, List, Literal, Optional
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class ConversationBase(BaseModel):
    title: Optional[str] = None


class ConversationCreate(ConversationBase):
    title: str = "新對話"


class Conversation(ConversationBase):
    id: UUID
    user_id: UUID
    tenant_id: UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MessageBase(BaseModel):
    role: Literal["user", "assistant", "system"]  # constrained to valid roles
    content: str


class MessageCreate(MessageBase):
    conversation_id: UUID


class Message(MessageBase):
    id: UUID
    conversation_id: UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChatRequest(BaseModel):
    question: str
    conversation_id: Optional[UUID] = None
    top_k: int = Field(default=3, ge=1, le=20, description="Number of KB chunks to retrieve")


class ChatResponse(BaseModel):
    request_id: str
    question: str
    answer: str
    conversation_id: UUID
    message_id: UUID
    company_policy: Optional[Dict[str, Any]] = None
    # labor_law is kept for backwards API compatibility; always None in current builds.
    # Remove once confirmed no client depends on it.
    labor_law: Optional[Dict[str, Any]] = None
    sources: List[Dict[str, Any]]
    notes: List[str]
    disclaimer: str


# ──────────── T7-5: Feedback ────────────

# Valid feedback categories — document here so callers know the contract.
FEEDBACK_CATEGORIES = (
    "wrong_answer",
    "incomplete",
    "outdated",
    "hallucination",
    "other",
)


class FeedbackCreate(BaseModel):
    message_id: UUID
    rating: Literal[1, 2] = Field(..., description="1 = 👎 negative, 2 = 👍 positive")
    category: Optional[Literal["wrong_answer", "incomplete", "outdated", "hallucination", "other"]] = None
    comment: Optional[str] = None


class FeedbackResponse(BaseModel):
    id: UUID
    message_id: UUID
    rating: int
    category: Optional[str] = None
    comment: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FeedbackCategoryCount(BaseModel):
    category: Optional[str] = None
    count: int


class FeedbackStats(BaseModel):
    total: int
    positive: int
    negative: int
    positive_rate: float
    categories: List[FeedbackCategoryCount]


# ──────────── T7-13: 搜尋結果 ────────────

class SearchResult(BaseModel):
    conversation_id: UUID
    conversation_title: Optional[str] = None
    message_id: UUID
    role: str
    content: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
