from typing import Optional
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, ConfigDict


# Audit Log Schemas
class AuditLogBase(BaseModel):
    action: str
    target_type: Optional[str] = None
    target_id: Optional[str] = None
    detail_json: Optional[dict] = None


class AuditLog(AuditLogBase):
    id: UUID
    tenant_id: UUID
    actor_user_id: Optional[UUID] = None
    ip_address: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# Usage Record Schemas
class UsageRecordBase(BaseModel):
    action_type: str
    input_tokens: int = 0
    output_tokens: int = 0
    pinecone_queries: int = 0
    embedding_calls: int = 0
    estimated_cost_usd: float = 0.0


class UsageRecord(UsageRecordBase):
    id: UUID
    tenant_id: UUID
    user_id: Optional[UUID] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UsageSummary(BaseModel):
    tenant_id: str
    total_input_tokens: int
    total_output_tokens: int
    total_pinecone_queries: int
    total_embedding_calls: int
    total_cost: float
    total_actions: int


class UsageByActionType(BaseModel):
    action_type: str
    count: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost: float
