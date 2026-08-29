"""Response models for the versioned Input capability contract."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

EvidenceState = Literal[
    "internally_verified",
    "environment_validation_pending",
    "transitional",
    "not_implemented",
]


class InputPolicy(BaseModel):
    scope: str
    accepted_modes: list[str]
    data_classifications: list[str]
    idempotency_key_max_chars: int = Field(gt=0)
    capture_manifest_max_bytes: int = Field(gt=0)
    core_capture: bool
    capture_modes: list[str]
    capture_policy_path: str
    generic_resumable_upload: bool
    resumable_part_size: int = Field(gt=0)
    resumable_min_part_size: int = Field(gt=0)
    resumable_max_part_size: int = Field(gt=0)
    resumable_max_parts: int = Field(gt=0)
    resumable_session_ttl_hours: int = Field(gt=0)
    video_allowed_codecs: list[str]
    audio_allowed_codecs: list[str]
    media_proxy_enabled: bool


class InputQuota(BaseModel):
    max_documents: int | None = None
    current_documents: int = 0
    remaining_documents: int | None = None
    max_storage_bytes: int | None = None
    current_storage_bytes: int = 0
    remaining_storage_bytes: int | None = None
    warnings: list[str] = Field(default_factory=list)


class InputFormatCapability(BaseModel):
    extension: str
    media_type: str
    parser_kind: str
    asset_kind: str
    capabilities: list[str]
    evidence_state: EvidenceState
    ui_default: bool
    quality_gate: dict[str, float | str] | None = None
    max_bytes: int = Field(gt=0)
    max_duration_seconds: int | None = Field(default=None, gt=0)
    processing_status: Literal["configured", "disabled", "degraded"]
    degradation_reasons: list[str]


class InputSourceCapability(BaseModel):
    key: str
    evidence_state: EvidenceState
    availability: str
    limitations: list[str]


class InputProviderState(BaseModel):
    key: str
    status: Literal["available", "configured", "disabled", "degraded", "not_probed"]
    runtime_verified: bool
    detail: str


class InputAdapterCapability(BaseModel):
    key: str
    version: str
    asset_kinds: list[str]
    capabilities: list[str]
    execution_boundary: str


class InputCapabilityResponse(BaseModel):
    contract_version: str
    registry_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    tenant_id: str
    policy: InputPolicy
    formats: list[InputFormatCapability]
    sources: list[InputSourceCapability]
    providers: list[InputProviderState]
    adapters: list[InputAdapterCapability]
    quota: InputQuota | None = None
