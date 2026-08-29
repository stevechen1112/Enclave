from typing import Any, Dict, List, Literal, Optional
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    # Evidence attachments (from RetrievalTrace.sources_json when present)
    sources: Optional[List[Dict[str, Any]]] = None

    model_config = ConfigDict(from_attributes=True)


class ChatRequest(BaseModel):
    question: str
    conversation_id: Optional[UUID] = None
    top_k: int = Field(default=3, ge=1, le=20, description="Number of KB chunks to retrieve")
    # MKA SceneContext — 限定設備／料號／產品等檢索範圍
    scene_context: Optional[Dict[str, Any]] = None
    knowledge_mode: Optional[Literal["spec_sop"]] = None
    # Legacy application scope. spec_sop is accepted only as a compatibility
    # alias and is normalized to the core knowledge_mode by the endpoint.
    module_key: Optional[str] = None

    @model_validator(mode="after")
    def validate_scope_contract(self):
        if (
            self.knowledge_mode is not None
            and self.module_key is not None
            and self.module_key != "spec_sop"
        ):
            raise ValueError(
                "knowledge_mode and application module_key are mutually exclusive"
            )
        return self


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
    category: Optional[Literal[
        "wrong_answer", "wrong_entity", "wrong_number", "wrong_version",
        "wrong_source", "incomplete", "unclear", "should_abstain",
        "false_abstain", "permission", "outdated", "hallucination", "other",
    ]] = None
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
