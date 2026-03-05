"""Schemas for SSO configuration and OAuth callback."""
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict

# ─── Tenant SSO Config ───

class SSOConfigBase(BaseModel):
    provider: str  # "google" | "microsoft"
    client_id: str
    enabled: bool = True
    allowed_domains: List[str] = Field(default_factory=list)
    auto_create_user: bool = True
    default_role: str = "employee"


class SSOConfigCreate(SSOConfigBase):
    client_secret: str


class SSOConfigUpdate(BaseModel):
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    enabled: Optional[bool] = None
    allowed_domains: Optional[List[str]] = None
    auto_create_user: Optional[bool] = None
    default_role: Optional[str] = None


class SSOConfigRead(SSOConfigBase):
    id: UUID
    tenant_id: UUID

    model_config = ConfigDict(from_attributes=True)


class SSOConfigPublic(BaseModel):
    """Safe projection — no secrets exposed to frontend."""
    provider: str
    enabled: bool

    model_config = ConfigDict(from_attributes=True)


# ─── OAuth callback ───

class OAuthCallbackRequest(BaseModel):
    """Frontend sends the authorization code + redirect_uri."""
    code: str
    redirect_uri: str
    tenant_id: UUID
    provider: str  # "google" | "microsoft"
    state: str
    code_verifier: str


class SSOStateRequest(BaseModel):
    tenant_id: UUID
    provider: str


class SSOStateResponse(BaseModel):
    state: str


# ─── SSO Discovery (auto-detect tenant by email domain) ───

class SSODiscoverRequest(BaseModel):
    email: str = Field(..., description="User's work email for domain-based tenant discovery")


class SSODiscoverProvider(BaseModel):
    provider: str
    client_id: str


class SSODiscoverResponse(BaseModel):
    tenant_id: UUID
    tenant_name: str
    providers: List[SSODiscoverProvider]
