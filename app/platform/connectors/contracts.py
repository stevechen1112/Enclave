"""Vendor-neutral, bounded connector SDK contracts.

Adapters discover immutable pages.  The orchestrator owns persistence, ACL
replacement and tombstones, preventing provider code from widening access or
hard-deleting canonical knowledge assets.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable, Protocol, TypeVar


class DeleteSemantics(StrEnum):
    TOMBSTONE = "tombstone"
    IGNORE = "ignore"


class ConnectorRateLimited(RuntimeError):
    def __init__(self, retry_after_seconds: float = 1.0):
        super().__init__("connector_rate_limited")
        self.retry_after_seconds = max(0.0, float(retry_after_seconds))


class ConnectorAuthExpired(RuntimeError):
    """The adapter must refresh credentials before continuing."""


@dataclass(frozen=True)
class ConnectorResourceRecord:
    source_record_id: str
    title: str
    content_hash: str
    content_uri: str | None = None
    file_path: str | None = None
    source_version: str | None = None
    parent_source_id: str | None = None
    mime_type: str = "application/octet-stream"
    metadata: dict[str, Any] = field(default_factory=dict)
    acl_entries: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class ConnectorPage:
    resources: tuple[ConnectorResourceRecord, ...]
    cursor: str | None
    snapshot_id: str
    snapshot_complete: bool
    delete_semantics: DeleteSemantics = DeleteSemantics.TOMBSTONE


class ConnectorSource(Protocol):
    def discover(self, *, cursor: str | None, limit: int) -> ConnectorPage: ...

    def fetch(self, resource: ConnectorResourceRecord, destination: str) -> str: ...


T = TypeVar("T")


def retry_connector_call(
    operation: Callable[[], T],
    *,
    attempts: int = 3,
    max_wait_seconds: float = 30.0,
    sleep: Callable[[float], None] = time.sleep,
    refresh_credentials: Callable[[], None] | None = None,
) -> T:
    """Retry rate limits and one credential refresh with bounded waiting."""

    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    refreshed = False
    for attempt in range(attempts):
        try:
            return operation()
        except ConnectorAuthExpired:
            if refreshed or refresh_credentials is None or attempt + 1 >= attempts:
                raise
            refresh_credentials()
            refreshed = True
        except ConnectorRateLimited as exc:
            if attempt + 1 >= attempts:
                raise
            sleep(min(exc.retry_after_seconds, max_wait_seconds))
    raise RuntimeError("connector_retry_exhausted")
