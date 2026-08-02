"""
P1 — RetrievalFacade

單一知識讀取入口：強制 AuthorizationContext + Resource PEP + 統一 CitationBuilder。
下游（KB canonical / Gateway fan-out）不得再各自發明第二套 citation 或略過 authz。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.authorization import AuthorizationContext
from app.gateway.citation import CitationBuilder
from app.gateway.contracts import ChunkResult, Citation, SearchDomain

logger = logging.getLogger(__name__)


@dataclass
class RetrievalResult:
    results: List[Dict[str, Any]] = field(default_factory=list)
    chunk_results: List[ChunkResult] = field(default_factory=list)
    citations: List[Citation] = field(default_factory=list)
    mode: str = "canonical"
    total: int = 0
    # A6: propagate gateway audit so chat/SSE can persist providers_called.
    audit_trail: Optional[Any] = None
    gateway_status: Optional[str] = None  # success | partial | error

    def to_context_parts(self) -> List[str]:
        parts = []
        for i, r in enumerate(self.results):
            text = r.get("text") or r.get("content") or ""
            doc = str(r.get("document_id") or "")[:8]
            parts.append(f"[來源 {i+1}] (doc:{doc})\n{text}")
        return parts


class RetrievalFacade:
    """Canonical retrieval + authorization + citation orchestration."""

    def __init__(self):
        self._citation = CitationBuilder()

    def search(
        self,
        *,
        authz: AuthorizationContext,
        query: str,
        top_k: int = 10,
        mode: str = "hybrid",
        db: Optional[Session] = None,
        scope: Optional[Dict[str, Any]] = None,
    ) -> RetrievalResult:
        """
        Synchronous canonical KB search (pgvector).

        authz is required — callers must not pass None.
        """
        if authz is None:
            raise ValueError("AuthorizationContext is required for RetrievalFacade.search")
        from app.services.kb_retrieval import KnowledgeBaseRetriever

        raw = KnowledgeBaseRetriever().search(
            tenant_id=authz.tenant_id,
            query=query,
            top_k=top_k,
            mode=mode,
            authz=authz,
            filter_dict=scope,
        )
        chunks = self._dicts_to_chunks(raw)
        citations = self._citation.build(
            chunks,
            acl_revision=getattr(authz, "policy_revision", 1) or 1,
            db=db,
        )
        return RetrievalResult(
            results=raw,
            chunk_results=chunks,
            citations=citations,
            mode=mode,
            total=len(raw),
        )

    async def search_gateway(
        self,
        *,
        authz: AuthorizationContext,
        query: str,
        top_k: int = 10,
        domain: SearchDomain = SearchDomain.HYBRID,
        scope: Optional[Dict[str, Any]] = None,
        db: Optional[Session] = None,
    ) -> RetrievalResult:
        """Async Gateway fan-out search with unified citations."""
        if authz is None:
            raise ValueError("AuthorizationContext is required for RetrievalFacade.search_gateway")
        from app.gateway.runtime import get_configured_gateway_router

        response = await get_configured_gateway_router().search(
            authz=authz,
            query=query,
            domain=domain,
            top_k=top_k,
            scope=scope,
            db=db,
        )
        errors = list(getattr(response, "errors", None) or [])
        if getattr(response, "status", None) in ("error", "partial") and any(
            getattr(e, "code", None) == "no_adapter" for e in errors
        ):
            raise RuntimeError("gateway_no_adapter")
        if getattr(response, "status", None) == "error" and not (response.results or []):
            msgs = "; ".join(getattr(e, "message", str(e)) for e in errors) or "gateway_error"
            raise RuntimeError(msgs)

        citations = self._citation.build(
            list(response.results or []),
            acl_revision=getattr(authz, "policy_revision", 1) or 1,
            db=db,
        )
        results = [
            {
                "id": r.id,
                "document_id": r.document_id,
                "text": r.content,
                "content": r.content,
                "score": r.score,
                "provider": r.provider,
                "metadata": r.metadata or {},
            }
            for r in (response.results or [])
        ]
        return RetrievalResult(
            results=results,
            chunk_results=list(response.results or []),
            citations=citations,
            mode=str(domain),
            total=len(results),
            audit_trail=getattr(response, "audit_trail", None),
            gateway_status=getattr(response, "status", None),
        )

    @staticmethod
    def _dicts_to_chunks(raw: List[Dict[str, Any]]) -> List[ChunkResult]:
        chunks: List[ChunkResult] = []
        for r in raw:
            meta = dict(r.get("metadata") or {})
            if r.get("chunk_hash"):
                meta.setdefault("chunk_hash", r["chunk_hash"])
            if r.get("content_hash"):
                meta.setdefault("content_hash", r["content_hash"])
            chunks.append(
                ChunkResult(
                    id=str(r.get("id") or r.get("chunk_id") or ""),
                    document_id=str(r.get("document_id") or ""),
                    content=r.get("text") or r.get("content") or "",
                    score=float(r.get("score") or 0.0),
                    provider=r.get("provider") or "enclave",
                    provider_version=str(r.get("provider_version") or ""),
                    result_type=r.get("result_type") or "chunk",
                    document_revision=r.get("document_revision") or meta.get("version"),
                    metadata=meta,
                )
            )
        return chunks


_facade: Optional[RetrievalFacade] = None


def get_retrieval_facade() -> RetrievalFacade:
    global _facade
    if _facade is None:
        _facade = RetrievalFacade()
    return _facade
