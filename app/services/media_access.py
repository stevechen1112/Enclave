"""Short-lived, resource-bound tokens for browser media elements."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from jose import JWTError, jwt

from app.config import settings


def create_media_token(
    *,
    tenant_id: UUID,
    user_id: UUID,
    resource_kind: str,
    resource_id: UUID,
    expires_seconds: int = 900,
) -> str:
    return jwt.encode(
        {
            "exp": datetime.now(UTC) + timedelta(seconds=expires_seconds),
            "sub": str(user_id),
            "tenant_id": str(tenant_id),
            "scope": "media.read",
            "resource_kind": resource_kind,
            "resource_id": str(resource_id),
        },
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )


def decode_media_token(
    token: str, *, resource_kind: str, resource_id: UUID
) -> dict[str, Any] | None:
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
    except JWTError:
        return None
    if (
        payload.get("scope") != "media.read"
        or payload.get("resource_kind") != resource_kind
        or payload.get("resource_id") != str(resource_id)
        or not payload.get("tenant_id")
    ):
        return None
    return payload
