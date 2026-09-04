"""Fail-closed tenant routing for the media-v2 shadow pipeline."""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from app.config import settings


def parse_tenant_allowlist(raw: str | Iterable[str] | None) -> frozenset[str]:
    """Normalize an explicit tenant UUID allowlist; invalid entries are ignored."""

    values = raw.split(",") if isinstance(raw, str) else (raw or ())
    normalized: set[str] = set()
    for value in values:
        candidate = str(value).strip()
        if not candidate:
            continue
        try:
            normalized.add(str(UUID(candidate)))
        except (TypeError, ValueError, AttributeError):
            continue
    return frozenset(normalized)


def media_v2_enabled_for(tenant_id: UUID | str) -> bool:
    """Require both the global kill switch and explicit tenant enrollment."""

    if not settings.MEDIA_PIPELINE_V2:
        return False
    try:
        normalized_tenant_id = str(UUID(str(tenant_id)))
    except (TypeError, ValueError, AttributeError):
        return False
    return normalized_tenant_id in parse_tenant_allowlist(
        settings.MEDIA_V2_TENANT_ALLOWLIST
    )


def media_capability_enabled_for(
    tenant_id: UUID | str, *, capability_enabled: bool
) -> bool:
    """A media-v2 capability cannot bypass tenant enrollment or its own switch."""

    return bool(capability_enabled and media_v2_enabled_for(tenant_id))
