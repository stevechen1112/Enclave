"""Versioned contracts for optional knowledge providers.

The platform owns request scope, tenant validation, fusion and citations. Domain
packs contribute typed candidates; they do not return trusted arbitrary rows.
Legacy mappings are accepted temporarily at the registry boundary so packs can
be migrated without creating a second retrieval path.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.orm import Session

from app.core.authorization import AuthorizationContext

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class KnowledgeContributionContext:
    """Request-scoped, policy-relevant inputs available to a provider."""

    authz: AuthorizationContext
    query: str
    db: Session | None
    top_k: int = 10
    scope: Mapping[str, Any] = field(default_factory=dict)
    domain: str = "hybrid"
    mode: str = "hybrid"

    def __post_init__(self) -> None:
        if self.top_k < 1:
            raise ValueError("top_k must be >= 1")
        object.__setattr__(self, "scope", MappingProxyType(dict(self.scope or {})))

    @property
    def has_explicit_kb_revision_scope(self) -> bool:
        return "kb_revision_id" in self.scope or "kb_revision_ids" in self.scope


@dataclass(frozen=True)
class KnowledgeCandidate:
    """A tenant-bound, citable candidate contributed by a domain pack."""

    id: str
    tenant_id: str
    content: str
    score: float
    canonical_resource_type: str
    canonical_resource_id: str
    result_type: str
    title: str
    provider: str
    provider_version: str
    document_id: str | None = None
    document_revision: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        required = {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "content": self.content,
            "canonical_resource_type": self.canonical_resource_type,
            "canonical_resource_id": self.canonical_resource_id,
            "result_type": self.result_type,
            "title": self.title,
            "provider": self.provider,
            "provider_version": self.provider_version,
        }
        for name, value in required.items():
            if not str(value or "").strip():
                raise ValueError(f"knowledge candidate {name} is required")
        if not math.isfinite(float(self.score)):
            raise ValueError("knowledge candidate score must be finite")
        if self.document_revision is not None and self.document_revision < 1:
            raise ValueError("document_revision must be >= 1")
        object.__setattr__(
            self, "metadata", MappingProxyType(dict(self.metadata or {}))
        )

    def to_retrieval_dict(self, *, provider_key: str) -> dict[str, Any]:
        metadata = dict(self.metadata)
        metadata.update(
            {
                "knowledge_provider_key": provider_key,
                "canonical_resource_type": self.canonical_resource_type,
                "canonical_resource_id": self.canonical_resource_id,
                "title": self.title,
                "provider_version": self.provider_version,
            }
        )
        return {
            "id": self.id,
            "score": float(self.score),
            "content": self.content,
            "text": self.content,
            "document_id": self.document_id,
            "document_revision": self.document_revision,
            "filename": self.title,
            "metadata": metadata,
            "provider": self.provider,
            "provider_version": self.provider_version,
            "result_type": self.result_type,
        }


@dataclass(frozen=True)
class KnowledgeProviderFailure:
    provider_key: str
    code: str
    retryable: bool = False


@dataclass(frozen=True)
class KnowledgeContributionBatch:
    candidates: tuple[KnowledgeCandidate, ...] = ()
    failures: tuple[KnowledgeProviderFailure, ...] = ()
    provider_keys: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "provider_keys", MappingProxyType(dict(self.provider_keys or {}))
        )

    @property
    def degraded(self) -> bool:
        return bool(self.failures)

    def to_retrieval_dicts(self) -> list[dict[str, Any]]:
        return [
            candidate.to_retrieval_dict(
                provider_key=self.provider_keys.get(candidate.id, candidate.provider)
            )
            for candidate in self.candidates
        ]


@runtime_checkable
class KnowledgeProvider(Protocol):
    """A versioned domain pack that contributes governed candidates."""

    provider_key: str
    provider_version: str
    capability_keys: tuple[str, ...]

    def contribute(
        self, context: KnowledgeContributionContext
    ) -> Iterable[KnowledgeCandidate | Mapping[str, Any]]:
        """Return candidates already filtered for domain applicability."""


class KnowledgeProviderRegistry:
    """Ordered registry that validates and isolates optional providers."""

    def __init__(self, providers: Iterable[KnowledgeProvider] = ()) -> None:
        self._providers: dict[str, KnowledgeProvider] = {}
        for provider in providers:
            self.register(provider)

    def register(self, provider: KnowledgeProvider) -> None:
        key = str(getattr(provider, "provider_key", "") or "").strip()
        version = str(getattr(provider, "provider_version", "") or "").strip()
        capabilities = tuple(getattr(provider, "capability_keys", ()) or ())
        if not key:
            raise ValueError("knowledge provider_key is required")
        if not version:
            raise ValueError(f"knowledge provider_version is required: {key}")
        if not capabilities or any(not str(item).strip() for item in capabilities):
            raise ValueError(f"knowledge provider capability_keys are required: {key}")
        if not callable(getattr(provider, "contribute", None)):
            raise TypeError(f"knowledge provider contribute() is required: {key}")
        if key in self._providers:
            raise ValueError(f"duplicate knowledge provider_key: {key}")
        self._providers[key] = provider

    @property
    def provider_keys(self) -> tuple[str, ...]:
        return tuple(self._providers)

    def contribute(
        self,
        *,
        authz: AuthorizationContext,
        query: str,
        db: Session | None,
        top_k: int,
        scope: Mapping[str, Any] | None = None,
        domain: str = "hybrid",
        mode: str = "hybrid",
    ) -> KnowledgeContributionBatch:
        context = KnowledgeContributionContext(
            authz=authz,
            query=query,
            db=db,
            top_k=top_k,
            scope=scope or {},
            domain=domain,
            mode=mode,
        )
        candidates: list[KnowledgeCandidate] = []
        candidate_provider_keys: dict[str, str] = {}
        failures: list[KnowledgeProviderFailure] = []
        seen_ids: set[str] = set()
        for key, provider in self._providers.items():
            try:
                rows = provider.contribute(context) or []
                provider_candidates: list[KnowledgeCandidate] = []
                for row in rows:
                    candidate = self._normalize_candidate(row, provider=provider)
                    if candidate.tenant_id != str(authz.tenant_id):
                        raise ValueError(
                            "candidate tenant_id does not match request tenant"
                        )
                    if candidate.provider_version != str(provider.provider_version):
                        raise ValueError(
                            "candidate provider_version does not match registry"
                        )
                    from app.services.asset_visibility import (
                        candidate_asset_access_allows,
                    )

                    if not candidate_asset_access_allows(
                        db,
                        tenant_id=candidate.tenant_id,
                        metadata=candidate.metadata,
                        authz=authz,
                    ):
                        continue
                    if candidate.id in seen_ids or any(
                        item.id == candidate.id for item in provider_candidates
                    ):
                        raise ValueError(f"duplicate candidate id: {candidate.id}")
                    provider_candidates.append(candidate)
                    if len(provider_candidates) >= top_k:
                        break
                for candidate in provider_candidates:
                    seen_ids.add(candidate.id)
                    candidate_provider_keys[candidate.id] = key
                candidates.extend(provider_candidates)
            except (TypeError, ValueError, KeyError):
                logger.exception("knowledge provider returned invalid output: %s", key)
                failures.append(
                    KnowledgeProviderFailure(
                        provider_key=key,
                        code="invalid_output",
                        retryable=False,
                    )
                )
            except Exception:
                logger.exception("knowledge provider unavailable: %s", key)
                failures.append(
                    KnowledgeProviderFailure(
                        provider_key=key,
                        code="provider_unavailable",
                        retryable=True,
                    )
                )

        return KnowledgeContributionBatch(
            candidates=tuple(candidates),
            failures=tuple(failures),
            provider_keys=MappingProxyType(candidate_provider_keys),
        )

    @staticmethod
    def _normalize_candidate(
        row: KnowledgeCandidate | Mapping[str, Any], *, provider: KnowledgeProvider
    ) -> KnowledgeCandidate:
        if isinstance(row, KnowledgeCandidate):
            return row
        if not isinstance(row, Mapping):
            raise TypeError(
                "knowledge provider rows must be KnowledgeCandidate or mapping"
            )
        metadata = dict(row.get("metadata") or {})
        resource_id = (
            row.get("canonical_resource_id")
            or metadata.get("canonical_resource_id")
            or row.get("document_id")
            or row.get("id")
        )
        return KnowledgeCandidate(
            id=str(row.get("id") or ""),
            tenant_id=str(row.get("tenant_id") or metadata.get("tenant_id") or ""),
            content=str(row.get("text") or row.get("content") or ""),
            score=float(row.get("score") or 0.0),
            canonical_resource_type=str(
                row.get("canonical_resource_type")
                or metadata.get("canonical_resource_type")
                or "document"
            ),
            canonical_resource_id=str(resource_id or ""),
            result_type=str(row.get("result_type") or "chunk"),
            title=str(
                row.get("filename")
                or row.get("title")
                or metadata.get("filename")
                or metadata.get("title")
                or ""
            ),
            provider=str(row.get("provider") or provider.provider_key),
            provider_version=str(
                row.get("provider_version") or provider.provider_version
            ),
            document_id=(str(row["document_id"]) if row.get("document_id") else None),
            document_revision=(
                int(row["document_revision"])
                if row.get("document_revision") is not None
                else None
            ),
            metadata=metadata,
        )
