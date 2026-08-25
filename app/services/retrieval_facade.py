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
        kb_revision_id = (filters or {}).get("kb_revision_id")
        if kb_revision_id is not None and not isinstance(kb_revision_id, UUID):
            try:
                kb_revision_id = UUID(str(kb_revision_id))
            except (TypeError, ValueError) as exc:
                raise ValueError("kb_revision_id must be a UUID") from exc
        kb_revision_ids = []
        for value in (filters or {}).get("kb_revision_ids") or []:
            try: kb_revision_ids.append(UUID(str(value)))
            except (TypeError, ValueError) as exc: raise ValueError("kb_revision_ids must contain UUIDs") from exc
        return self._catalog.search(
            tenant_id=authz.tenant_id,
            query=query,
            top_k=top_k,
            genre_filter=genre_filter,
            kb_revision_id=kb_revision_id,
            kb_revision_ids=kb_revision_ids if "kb_revision_ids" in (filters or {}) else None,
            authz=authz,
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

        self._inject_approved_knowhow(authz=authz, raw=raw, db=db, query=query)
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
        scope: Optional[Dict[str, Any]] = None,
        db: Optional[Session] = None,
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

        own_session = db is None
        db = db or SessionLocal()
        try:
            rows_query = (
                db.query(DocumentChunk)
                .join(Document, DocumentChunk.document_id == Document.id)
                .filter(
                    Document.filename == filename,
                    DocumentChunk.tenant_id == authz.tenant_id,
                )
            )
            raw_revision_ids = []
            if (scope or {}).get("kb_revision_id"):
                raw_revision_ids.append((scope or {})["kb_revision_id"])
            raw_revision_ids.extend((scope or {}).get("kb_revision_ids") or [])
            from app.services.document_visibility import apply_document_visibility, deny_set_allows
            rows_query = apply_document_visibility(
                rows_query, authz=authz, db=db,
                require_completed=not (raw_revision_ids or "kb_revision_ids" in (scope or {})),
            )
            if raw_revision_ids or "kb_revision_ids" in (scope or {}):
                from app.models.knowledge_engine import KnowledgeBaseRevisionDocument
                from app.services.document_readiness import ready_revision_pairs

                revision_ids = [UUID(str(value)) for value in raw_revision_ids]
                rows_query = rows_query.join(
                    KnowledgeBaseRevisionDocument,
                    (KnowledgeBaseRevisionDocument.document_id == DocumentChunk.document_id)
                    & (KnowledgeBaseRevisionDocument.document_revision == DocumentChunk.document_revision),
                ).filter(
                    KnowledgeBaseRevisionDocument.tenant_id == authz.tenant_id,
                    KnowledgeBaseRevisionDocument.kb_revision_id.in_(revision_ids),
                )
                ready_pairs = ready_revision_pairs(
                    db, tenant_id=authz.tenant_id, kb_revision_ids=revision_ids
                )
                if ready_pairs:
                    from sqlalchemy import tuple_

                    rows_query = rows_query.filter(
                        tuple_(
                            DocumentChunk.document_id,
                            DocumentChunk.document_revision,
                        ).in_(ready_pairs)
                    )
                else:
                    rows_query = rows_query.filter(False)
            else:
                rows_query = rows_query.filter(DocumentChunk.document_revision == Document.version)
            rows = [row for row in (
                rows_query.order_by(DocumentChunk.chunk_index.asc())
                .limit(n)
                .all()
            ) if deny_set_allows(row.document_id, authz=authz)]
            return [
                {
                    "id": str(c.id),
                    "score": None,
                    "content": c.text or "",
                    "document_id": str(c.document_id),
                    "document_revision": c.document_revision,
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
            if own_session:
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
        response.results = self._filter_gateway_visibility(
            response.results or [], authz=authz, scope=scope, db=db
        )
        errors = list(getattr(response, "errors", None) or [])
        if getattr(response, "status", None) in ("error", "partial") and any(
            getattr(e, "code", None) == "no_adapter" for e in errors
        ):
            raise RuntimeError("gateway_no_adapter")
        if getattr(response, "status", None) == "error" and not (response.results or []):
            msgs = "; ".join(getattr(e, "message", str(e)) for e in errors) or "gateway_error"
            raise RuntimeError(msgs)

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
        self._inject_approved_knowhow(authz=authz, raw=results, db=db, query=query)
        chunks = self._dicts_to_chunks(results)
        citations = self._citation.build(
            chunks,
            acl_revision=getattr(authz, "policy_revision", 1) or 1,
            db=db,
        )
        return RetrievalResult(
            results=results,
            chunk_results=chunks,
            citations=citations,
            mode=str(domain),
            total=len(results),
            audit_trail=getattr(response, "audit_trail", None),
            gateway_status=getattr(response, "status", None),
        )

    @staticmethod
    def _filter_gateway_visibility(results, *, authz: AuthorizationContext, scope, db=None):
        """Revalidate every sidecar hit against canonical document visibility.

        Adapters are defense-in-depth, not the policy authority.  When an
        immutable KB revision scope exists, a result without a canonical
        document/revision mapping cannot participate in an answer.
        """
        if not results:
            return []
        from app.db.session import SessionLocal
        from app.models.document import Document
        from app.services.document_readiness import ready_revision_pairs
        from app.services.document_visibility import apply_document_visibility, deny_set_allows

        own = db is None
        session = db or SessionLocal()
        try:
            by_uuid = {}
            passthrough = []
            for result in results:
                try:
                    doc_id = UUID(str(result.document_id))
                except (TypeError, ValueError, AttributeError):
                    passthrough.append(result)
                    continue
                by_uuid.setdefault(doc_id, []).append(result)

            scope_is_explicit = "kb_revision_ids" in (scope or {})
            visible_query = apply_document_visibility(
                session.query(Document.id, Document.version), authz=authz, db=session,
                require_completed=not scope_is_explicit,
            ).filter(Document.id.in_(list(by_uuid)))
            visible_current = {
                doc_id: int(version)
                for doc_id, version in visible_query.all()
                if deny_set_allows(doc_id, authz=authz)
            }

            raw_revision_ids = (scope or {}).get("kb_revision_ids") or []
            if scope_is_explicit:
                try:
                    revision_ids = [UUID(str(value)) for value in raw_revision_ids]
                except (TypeError, ValueError):
                    return []
                if not revision_ids:
                    return []
                membership_rows = ready_revision_pairs(
                    session,
                    tenant_id=authz.tenant_id,
                    kb_revision_ids=revision_ids,
                )
                allowed_revisions = {}
                for doc_id, revision in membership_rows:
                    if doc_id not in visible_current:
                        continue
                    allowed_revisions.setdefault(doc_id, set()).add(int(revision))
            else:
                allowed_revisions = {doc_id: {revision} for doc_id, revision in visible_current.items()}

            kept = []
            for doc_id, doc_results in by_uuid.items():
                valid_revisions = allowed_revisions.get(doc_id, set())
                for result in doc_results:
                    meta = result.metadata or {}
                    raw_revision = result.document_revision or meta.get("document_revision") or meta.get("version")
                    if raw_revision is None and len(valid_revisions) == 1:
                        raw_revision = next(iter(valid_revisions))
                        result.document_revision = raw_revision
                    try:
                        revision = int(raw_revision)
                    except (TypeError, ValueError):
                        continue
                    if revision in valid_revisions:
                        kept.append(result)

            # Legacy mode may still surface an object-level-authorized connector
            # record.  Revision-scoped production reads never do.
            if not scope_is_explicit:
                kept.extend(passthrough)
            return kept
        finally:
            if own:
                session.close()

    @staticmethod
    def _inject_approved_knowhow(
        *,
        authz: AuthorizationContext,
        raw: List[Dict[str, Any]],
        db: Optional[Session],
        query: str = "",
    ) -> None:
        """Append approved cards from the current request session only.

        Authority-based scoring (§7.3):
        - authority_level 100 (formal_policy) → score * 1.0
        - authority_level 90 (approved_sop) → score * 0.95
        - authority_level 80 (approved_spec) → score * 0.90
        - authority_level 70 (approved_case) → score * 0.85
        - authority_level 60 (approved_knowhow) → score * 0.80
        - authority_level 20 (external_reference) → score * 0.50
        Draft (0) is excluded by draft isolation.
        """
        from app.config import settings

        if not (
            settings.KNOWHOW_CARD_ENABLED
            and settings.KNOWHOW_DRAFT_ISOLATION
            and db is not None
        ):
            return
        from app.services.mka_persistence import MKARepository

        # Authority score multiplier mapping (§7.3)
        AUTHORITY_MULTIPLIER = {
            100: 1.0,   # formal_policy
            90: 0.95,   # approved_sop
            80: 0.90,   # approved_spec_or_contract
            70: 0.85,   # approved_case
            60: 0.80,   # approved_knowhow
            20: 0.50,   # external_reference
        }

        for card in MKARepository(db).list_approved_knowhow(
            tenant_id=authz.tenant_id
        ):
            if not RetrievalFacade._knowhow_applies(card, authz=authz, query=query):
                continue
            authority = getattr(card, "authority_level", 60) or 60
            multiplier = AUTHORITY_MULTIPLIER.get(authority, 0.80)
            base_score = 0.85
            adjusted_score = round(base_score * multiplier, 4)

            raw.append(
                {
                    "id": f"knowhow:{card.card_id}",
                    "score": adjusted_score,
                    "content": (
                        f"[知識卡] {card.title}\n{card.summary or ''}\n"
                        + "\n".join(card.steps or [])
                    ),
                    # A knowledge card is itself a durable canonical record.
                    # Its UUID + version form a complete citation even when the
                    # source was an interview rather than an uploaded document.
                    "document_id": str(card.id),
                    "document_revision": int(card.version or 1),
                    "filename": f"knowhow:{card.title}",
                    "chunk_index": 0,
                    "metadata": {
                        "type": "knowhow_card",
                        "card_id": card.card_id,
                        "version": card.version,
                        "document_revision": int(card.version or 1),
                        "authority_level": authority,
                        "artifact_type": "knowhow",
                        "source_system": "knowhow",
                        "source_record_id": card.card_id,
                        "source_document_id": card.source_document_id,
                    },
                    "source": "knowhow",
                    "provider": "knowhow",
                    "result_type": "knowhow",
                }
            )

        # Re-sort: know-how cards 按 authority 排序後插入適當位置，
        # 但不破壞原有 rerank 排序的 chunk 順序。
        # 策略：將 know-how card 按 authority-adjusted score 插入，
        # 保留原有 chunk 的相對順序。
        original_chunks = [r for r in raw if r.get("source") != "knowhow"]
        knowhow_entries = [r for r in raw if r.get("source") == "knowhow"]
        # know-how card 之間按 score 降序
        knowhow_entries.sort(key=lambda r: r.get("score", 0), reverse=True)
        # 重新組裝：原有 chunk 在前，know-how card 在後
        # （know-how 的 score 通常低於 rerank 後的 chunk，自然排在後面）
        raw.clear()
        raw.extend(original_chunks)
        raw.extend(knowhow_entries)

    @staticmethod
    def _knowhow_applies(card, *, authz: AuthorizationContext, query: str) -> bool:
        """Fail closed for role/entity-scoped and high-risk field knowledge."""
        query_key = (query or "").casefold().replace(" ", "")
        roles = {str(role).casefold() for role in (authz.role_ids or [])}
        applicable_roles = {str(role).casefold() for role in (card.applicable_roles or [])}
        if applicable_roles and not roles.intersection(applicable_roles):
            return False

        # Scoped cards require the relevant equipment/product/customer to be
        # present in the question.  Silence is ambiguity, not permission to
        # apply a specific machine's technique globally.
        for values in (card.equipment_ids or [], card.product_ids or [], card.customer_ids or []):
            normalized = [str(value).casefold().replace(" ", "") for value in values if value]
            if normalized and not any(value in query_key for value in normalized):
                return False

        authority = int(card.authority_level or 0)
        if str(card.risk_level or "").casefold() == "high" and authority < 90:
            return False
        if any(token in query_key for token in ("工安", "安全", "危險", "停機", "品質放行")) and authority < 90:
            return False
        return True

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
