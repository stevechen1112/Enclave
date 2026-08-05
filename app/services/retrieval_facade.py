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
from app.services.catalog_retrieval import CatalogRetriever, RetrievalHit, get_catalog_retriever
from app.services.query_plan import is_inventory_query  # noqa: F401 — re-export 相容

logger = logging.getLogger(__name__)

# is_inventory_query 事實來源：app.services.query_plan（F4 QueryPlan）。


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
        from app.config import settings

        # P0-1：Context Fitting（feature-flagged）
        if settings.CONTEXT_FITTING_ENABLED:
            from app.services.context_fitting import fit_context
            fitted = fit_context(
                self.results,
                token_budget=settings.CONTEXT_FITTING_TOKEN_BUDGET,
            )
            return fitted.parts

        # 預設路徑：無 token 預算，逐 chunk 串接（原行為）
        parts = []
        for i, r in enumerate(self.results):
            text = r.get("text") or r.get("content") or ""
            doc = str(r.get("document_id") or "")[:8]
            parts.append(f"[來源 {i+1}] (doc:{doc})\n{text}")
        return parts


class RetrievalFacade:
    """Canonical retrieval + authorization + citation orchestration."""

    def __init__(self, catalog: Optional[CatalogRetriever] = None):
        self._citation = CitationBuilder()
        self._catalog = catalog or get_catalog_retriever()

    def search_catalog(
        self,
        *,
        authz: AuthorizationContext,
        query: str,
        top_k: int = 50,
        filters: Optional[Dict[str, Any]] = None,
        db: Optional[Session] = None,
    ) -> List[RetrievalHit]:
        """文件層（catalog）檢索——ADR-008 契約 1。

        回答「有哪些檔」類問題；只回 completed 且未 tombstone 的文件。
        """
        if authz is None:
            raise ValueError("AuthorizationContext is required for RetrievalFacade.search_catalog")
        genre_filter = (filters or {}).get("genres")
        return self._catalog.search(
            tenant_id=authz.tenant_id,
            query=query,
            top_k=top_k,
            genre_filter=genre_filter,
            db=db,
        )

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

        # P2-1：Know-how Card draft isolation — draft 不可被命中
        from app.config import settings
        if settings.KNOWHOW_CARD_ENABLED and settings.KNOWHOW_DRAFT_ISOLATION:
            from app.services.knowhow_card import get_knowhow_manager
            mgr = get_knowhow_manager()
            indexable_cards = mgr.get_indexable_cards()
            if indexable_cards:
                # 將 approved know-how cards 注入檢索結果
                for card in indexable_cards:
                    raw.append({
                        "id": f"knowhow:{card.card_id}",
                        "score": 0.85,
                        "content": f"[知識卡] {card.title}\n{card.summary}",
                        "document_id": card.source_document_id or card.card_id,
                        "filename": f"knowhow:{card.title}",
                        "chunk_index": 0,
                        "metadata": {"type": "knowhow_card", "card_id": card.card_id, "version": card.version},
                        "source": "knowhow",
                    })
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

    def get_document_head(
        self,
        *,
        authz: AuthorizationContext,
        filename: str,
        n: int = 2,
    ) -> List[Dict[str, Any]]:
        """取指定文件的前 n 個 chunk（文件頭部：標題/表頭/基本資料所在）。

        檔名鎖定查詢常問文件層級欄位（標題、日期、公司名稱），這些資訊
        固定在文件開頭，語意排名不一定排得進 top-k（2026-08-03 盲測
        E073 根因）。scoped 檢索應恆常附上文件頭部。
        """
        if authz is None:
            raise ValueError("AuthorizationContext is required")
        from app.db.session import SessionLocal
        from app.models.document import Document, DocumentChunk

        db = SessionLocal()
        try:
            rows = (
                db.query(DocumentChunk)
                .join(Document, DocumentChunk.document_id == Document.id)
                .filter(
                    Document.filename == filename,
                    Document.tombstoned_at.is_(None),
                    DocumentChunk.tenant_id == authz.tenant_id,
                )
                .order_by(DocumentChunk.chunk_index.asc())
                .limit(n)
                .all()
            )
            return [
                {
                    "id": str(c.id),
                    "score": None,
                    "content": c.text or "",
                    "document_id": str(c.document_id),
                    "filename": filename,
                    "chunk_index": c.chunk_index,
                    "metadata": c.metadata_json or {},
                    "source": "document_head",
                }
                for c in rows
            ]
        except Exception as exc:
            logger.warning("get_document_head failed for %s: %s", filename, exc)
            return []
        finally:
            db.close()

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
            # P0-1：攜帶 parent_chunk_id / chunk_index 供下游 context assembly 使用
            if r.get("parent_chunk_id"):
                meta.setdefault("parent_chunk_id", r["parent_chunk_id"])
            if r.get("chunk_index") is not None:
                meta.setdefault("chunk_index", r["chunk_index"])
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
