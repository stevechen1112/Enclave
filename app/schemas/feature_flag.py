"""Feature Flag schemas."""
from typing import Optional, List, Dict, Any
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict


class FeatureFlagBase(BaseModel):
    key: str
    description: str = ""
    enabled: bool = False
    rollout_percentage: int = 0
    allowed_tenant_ids: List[UUID] = Field(default_factory=list)
    allowed_environments: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict, alias="metadata_")


class FeatureFlagCreate(BaseModel):
    key: str
    description: str = ""
    enabled: bool = False
    rollout_percentage: int = 0
    allowed_tenant_ids: List[UUID] = Field(default_factory=list)
    allowed_environments: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class FeatureFlagUpdate(BaseModel):
    description: Optional[str] = None
    enabled: Optional[bool] = None
    rollout_percentage: Optional[int] = None
    allowed_tenant_ids: Optional[List[UUID]] = None
    allowed_environments: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None


class FeatureFlag(FeatureFlagBase):
    id: UUID

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class FeatureFlagEvaluation(BaseModel):
    key: str
    enabled: bool
