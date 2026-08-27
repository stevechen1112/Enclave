"""Versioned contracts for capability-routed ingestion adapters."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class IngestionRequest:
    tenant_id: str
    asset_id: str
    asset_revision_id: str
    asset_kind: str
    media_type: str
    content_uri: str
    requested_capabilities: tuple[str, ...]
    constraints: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "tenant_id",
            "asset_id",
            "asset_revision_id",
            "asset_kind",
            "media_type",
            "content_uri",
        ):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(f"{name} is required")
        if not self.requested_capabilities:
            raise ValueError("requested_capabilities is required")
        object.__setattr__(
            self, "requested_capabilities", tuple(self.requested_capabilities)
        )
        object.__setattr__(
            self, "constraints", MappingProxyType(dict(self.constraints or {}))
        )


@runtime_checkable
class IngestionAdapter(Protocol):
    adapter_key: str
    adapter_version: str
    supported_asset_kinds: tuple[str, ...]
    capability_keys: tuple[str, ...]
    execution_boundary: str
    priority: int

    def accepts(self, request: IngestionRequest) -> bool: ...


class IngestionAdapterRegistry:
    def __init__(self, adapters=()) -> None:
        self._adapters: dict[str, IngestionAdapter] = {}
        for adapter in adapters:
            self.register(adapter)

    def register(self, adapter: IngestionAdapter) -> None:
        key = str(getattr(adapter, "adapter_key", "") or "").strip()
        version = str(getattr(adapter, "adapter_version", "") or "").strip()
        kinds = tuple(getattr(adapter, "supported_asset_kinds", ()) or ())
        capabilities = tuple(getattr(adapter, "capability_keys", ()) or ())
        boundary = str(getattr(adapter, "execution_boundary", "") or "").strip()
        accepts = getattr(adapter, "accepts", None)
        if (
            not key
            or not version
            or not kinds
            or not capabilities
            or not boundary
            or not callable(accepts)
        ):
            raise ValueError("ingestion adapter metadata is incomplete")
        if key in self._adapters:
            raise ValueError(f"duplicate ingestion adapter_key: {key}")
        self._adapters[key] = adapter

    @property
    def adapter_keys(self) -> tuple[str, ...]:
        return tuple(self._adapters)

    def select(self, request: IngestionRequest) -> IngestionAdapter:
        candidates = [
            adapter
            for adapter in self._adapters.values()
            if request.asset_kind in adapter.supported_asset_kinds
            and set(request.requested_capabilities).issubset(adapter.capability_keys)
            and adapter.accepts(request)
        ]
        if not candidates:
            raise LookupError(
                f"no ingestion adapter for {request.asset_kind}: "
                + ",".join(request.requested_capabilities)
            )
        return min(
            candidates,
            key=lambda item: (-int(item.priority), item.adapter_key),
        )
