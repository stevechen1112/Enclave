from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class UploadSessionCreate(BaseModel):
    filename: str = Field(min_length=1, max_length=500)
    media_type: str = Field(default="application/octet-stream", min_length=3, max_length=255)
    byte_size: int = Field(gt=0)
    part_size: int | None = Field(default=None, gt=0)
    idempotency_key: str = Field(min_length=1, max_length=500)
    title: str | None = Field(default=None, max_length=500)
    department_id: UUID | None = None
    data_classification: str = "internal"
    context_metadata: dict[str, Any] = Field(default_factory=dict)
    expected_sha256: str | None = None

    @field_validator("expected_sha256")
    @classmethod
    def validate_sha256(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.lower()
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError("expected_sha256 must be 64 lowercase hex characters")
        return value


class UploadCommitRequest(BaseModel):
    expected_sha256: str | None = None

    @field_validator("expected_sha256")
    @classmethod
    def validate_sha256(cls, value: str | None) -> str | None:
        return UploadSessionCreate.validate_sha256(value)


class UploadPartResponse(BaseModel):
    part_number: int
    byte_size: int
    sha256: str


class UploadSessionResponse(BaseModel):
    id: UUID
    status: str
    filename: str
    media_type: str
    byte_size: int
    part_size: int
    total_parts: int
    received_bytes: int
    received_parts: int
    acknowledged_parts: list[UploadPartResponse]
    expires_at: datetime
    asset_id: UUID | None = None
    content_sha256: str | None = None
