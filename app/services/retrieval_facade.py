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

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.authorization import AuthorizationContext
from app.gateway.citation import CitationBuilder
from app.gateway.contracts import ChunkResult, Citation, SearchDomain
from app.gateway.fusion_policy import FusionPolicy
from app.platform.knowledge.providers import (
    KnowledgeProviderFailure,
    KnowledgeProviderRegistry,
)
from app.services.catalog_retrieval import (
    CatalogRetriever,
    RetrievalHit,
    get_catalog_retriever,
)
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
    provider_failures: List[KnowledgeProviderFailure] = field(default_factory=list)

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
            parts.append(f"[來源 {i + 1}] (doc:{doc})\n{text}")
        return parts


class RetrievalFacade:
    """Canonical retrieval + authorization + citation orchestration."""

    def __init__(
        self,
        providers: KnowledgeProviderRegistry,
        catalog: Optional[CatalogRetriever] = None,
    ):
        self._citation = CitationBuilder()
        self._fusion = FusionPolicy()
        self._catalog = catalog or get_catalog_retriever()
        self._providers = providers

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
            raise ValueError(
                "AuthorizationContext is required for RetrievalFacade.search_catalog"
            )
        genre_filter = (filters or {}).get("genres")
        kb_revision_id = (filters or {}).get("kb_revision_id")
        if kb_revision_id is not None and not isinstance(kb_revision_id, UUID):
            try:
                kb_revision_id = UUID(str(kb_revision_id))
            except (TypeError, ValueError) as exc:
                raise ValueError("kb_revision_id must be a UUID") from exc
        kb_revision_ids = []
        for value in (filters or {}).get("kb_revision_ids") or []:
            try:
                kb_revision_ids.append(UUID(str(value)))
            except (TypeError, ValueError) as exc:
                raise ValueError("kb_revision_ids must contain UUIDs") from exc
        return self._catalog.search(
            tenant_id=authz.tenant_id,
            query=query,
            top_k=top_k,
            genre_filter=genre_filter,
            kb_revision_id=kb_revision_id,
            kb_revision_ids=kb_revision_ids
            if "kb_revision_ids" in (filters or {})
            else None,
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
            raise ValueError(
                "AuthorizationContext is required for RetrievalFacade.search"
            )
        from app.services.kb_retrieval import KnowledgeBaseRetriever

        raw = KnowledgeBaseRetriever().search(
            tenant_id=authz.tenant_id,
            query=query,
            top_k=top_k,
            mode=mode,
            authz=authz,
            filter_dict=scope,
        )
        provider_batch = self._providers.contribute(
            authz=authz,
            query=query,
            db=db,
            top_k=top_k,
            scope=scope,
            domain=SearchDomain.DOCUMENT.value,
            mode=mode,
        )
        provider_chunks = self._dicts_to_chunks(provider_batch.to_retrieval_dicts())
        provider_chunks = self._filter_gateway_visibility(
            provider_chunks, authz=authz, scope=scope, db=db
        )
        legacy_chunks = self._dicts_to_chunks(raw) + provider_chunks
        from app.config import settings

        if settings.KNOWLEDGE_UNIT_READ_MODE == "enforce" and db is None:
            raise RuntimeError("knowledge authority enforce mode requires a DB session")
        authority_chunks: List[ChunkResult] = []
        if db is not None:
            try:
                authority_units = self._authority_units(
                    db=db, authz=authz, scope=scope, query=query
                )
                authority_chunks = self._authority_chunks_from_units(
                    units=authority_units,
                    query=query,
                    top_k=top_k,
                )
                if settings.KNOWLEDGE_UNIT_READ_MODE == "shadow":
                    from app.services.knowledge_authority_read import (
                        sealed_parity_report,
                    )

                    report = sealed_parity_report(
                        legacy_resource_ids=[
                            str(
                                chunk.metadata.get("canonical_resource_id")
                                or chunk.metadata.get("chunk_id")
                                or chunk.id
                            )
                            for chunk in legacy_chunks
                        ],
                        authority_units=authority_units,
                    )
                    if report["status"] == "mismatch":
                        logger.info("knowledge authority shadow mismatch: %s", report)
            except SQLAlchemyError:
                if settings.KNOWLEDGE_UNIT_READ_MODE == "enforce":
                    raise
                # During an additive deployment workers may briefly run before
                # the authority migration. Shadow mode must preserve the legacy
                # answer path while making the missing projection observable.
                logger.warning(
                    "knowledge authority shadow read unavailable", exc_info=True
                )
        chunks = (
            authority_chunks
            if settings.KNOWLEDGE_UNIT_READ_MODE == "enforce"
            else legacy_chunks
        )
        fusion = self._fusion.apply(chunks, query=query, top_k=top_k)
        chunks = fusion.results
        raw = self._chunks_to_dicts(chunks)

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
            gateway_status="partial" if provider_batch.degraded else "success",
            provider_failures=list(provider_batch.failures),
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
            from app.services.rls import apply_rls_context

            apply_rls_context(db, authz.tenant_id)
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
            from app.services.document_visibility import (
                apply_document_visibility,
                deny_set_allows,
            )

            rows_query = apply_document_visibility(
                rows_query,
                authz=authz,
                db=db,
                require_completed=not (
                    raw_revision_ids or "kb_revision_ids" in (scope or {})
                ),
            )
            if raw_revision_ids or "kb_revision_ids" in (scope or {}):
                from app.models.knowledge_engine import KnowledgeBaseRevisionDocument
                from app.services.document_readiness import ready_revision_pairs

                revision_ids = [UUID(str(value)) for value in raw_revision_ids]
                rows_query = rows_query.join(
                    KnowledgeBaseRevisionDocument,
                    (
                        KnowledgeBaseRevisionDocument.document_id
                        == DocumentChunk.document_id
                    )
                    & (
                        KnowledgeBaseRevisionDocument.document_revision
                        == DocumentChunk.document_revision
                    ),
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
                rows_query = rows_query.filter(
                    DocumentChunk.document_revision == Document.version
                )
            rows = [
                row
                for row in (
                    rows_query.order_by(DocumentChunk.chunk_index.asc()).limit(n).all()
                )
                if deny_set_allows(row.document_id, authz=authz)
            ]
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
            raise ValueError(
                "AuthorizationContext is required for RetrievalFacade.search_gateway"
            )
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
        if getattr(response, "status", None) == "error" and not (
            response.results or []
        ):
            msgs = (
                "; ".join(getattr(e, "message", str(e)) for e in errors)
                or "gateway_error"
            )
            raise RuntimeError(msgs)

        provider_batch = self._providers.contribute(
            authz=authz,
            query=query,
            db=db,
            top_k=top_k,
            scope=scope,
            domain=domain.value,
            mode="gateway",
        )
        audit_trail = getattr(response, "audit_trail", None)
        if audit_trail is not None:
            for key in self._providers.provider_keys:
                marker = f"knowledge:{key}"
                if marker not in audit_trail.providers_called:
                    audit_trail.providers_called.append(marker)
            for failure in provider_batch.failures:
                audit_trail.decisions.append(
                    f"knowledge_provider_degraded:{failure.provider_key}:{failure.code}"
                )
        provider_chunks = self._dicts_to_chunks(provider_batch.to_retrieval_dicts())
        provider_chunks = self._filter_gateway_visibility(
            provider_chunks, authz=authz, scope=scope, db=db
        )
        chunks = list(response.results or []) + provider_chunks
        fusion = self._fusion.apply(chunks, query=query, top_k=top_k)
        chunks = fusion.results
        results = self._chunks_to_dicts(chunks)
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
            audit_trail=audit_trail,
            gateway_status=(
                "partial"
                if provider_batch.degraded
                and getattr(response, "status", None) == "success"
                else getattr(response, "status", None)
            ),
            provider_failures=list(provider_batch.failures),
        )

    @staticmethod
    def _authority_units(
        *,
        db: Session,
        authz: AuthorizationContext,
        scope: Optional[Dict[str, Any]],
        query: str | None = None,
    ):
        from app.services.knowledge_authority_read import list_active_knowledge_units

        raw_scope: List[Any] = []
        explicit = False
        if "kb_revision_id" in (scope or {}):
            explicit = True
            raw_scope.append((scope or {}).get("kb_revision_id"))
        if "kb_revision_ids" in (scope or {}):
            explicit = True
            raw_scope.extend((scope or {}).get("kb_revision_ids") or [])
        revision_ids = [UUID(str(item)) for item in raw_scope if item]
        return list_active_knowledge_units(
            db,
            authz=authz,
            kb_revision_ids=revision_ids if explicit else None,
            query_text=query,
        )

    @classmethod
    def _authority_chunks(
        cls,
        *,
        db: Session,
        authz: AuthorizationContext,
        query: str,
        scope: Optional[Dict[str, Any]],
        top_k: int,
    ) -> List[ChunkResult]:
        return cls._authority_chunks_from_units(
            units=cls._authority_units(db=db, authz=authz, scope=scope, query=query),
            query=query,
            top_k=top_k,
        )

    @classmethod
    def _authority_chunks_from_units(
        cls,
        *,
        units,
        query: str,
        top_k: int,
    ) -> List[ChunkResult]:
        terms = {term.lower() for term in query.split() if term.strip()}
        scored = []
        for unit in units:
            haystack = f"{unit.title} {unit.content}".lower()
            score = (
                sum(1 for term in terms if term in haystack) / max(len(terms), 1)
                if terms
                else 0.0
            )
            metadata = dict(unit.metadata)
            metadata.update(
                {
                    "knowledge_unit_id": str(unit.unit_id),
                    "knowledge_unit_revision_id": str(unit.unit_revision_id),
                    "knowledge_release_id": str(unit.release_id),
                    "canonical_resource_type": unit.source_resource_type,
                    "canonical_resource_id": unit.source_resource_id,
                    "source_asset_id": (
                        str(unit.source_asset_id) if unit.source_asset_id else None
                    ),
                    "source_asset_revision_id": (
                        str(unit.source_asset_revision_id)
                        if unit.source_asset_revision_id
                        else None
                    ),
                    "source_artifact_id": (
                        str(unit.source_artifact_id)
                        if unit.source_artifact_id
                        else None
                    ),
                }
            )
            scored.append(
                {
                    "id": str(unit.unit_revision_id),
                    "score": score,
                    "content": unit.content,
                    "text": unit.content,
                    "document_id": metadata.get("document_id"),
                    "document_revision": metadata.get("document_revision"),
                    "filename": unit.title,
                    "metadata": metadata,
                    "provider": "knowledge_authority",
                    "provider_version": "1.0",
                    "result_type": unit.unit_type,
                }
            )
        scored.sort(key=lambda row: (-float(row["score"]), str(row["id"])))
        return cls._dicts_to_chunks(scored[:top_k])

    @staticmethod
    def _filter_gateway_visibility(
        results, *, authz: AuthorizationContext, scope, db=None
    ):
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
        from app.services.document_visibility import (
            apply_document_visibility,
            deny_set_allows,
        )

        own = db is None
        session = db or SessionLocal()
        try:
            from app.services.rls import apply_rls_context

            apply_rls_context(session, authz.tenant_id)
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
            scope_is_explicit = scope_is_explicit or "kb_revision_id" in (scope or {})
            if not by_uuid:
                return [] if scope_is_explicit else passthrough
            visible_query = apply_document_visibility(
                session.query(Document.id, Document.version),
                authz=authz,
                db=session,
                require_completed=not scope_is_explicit,
            ).filter(Document.id.in_(list(by_uuid)))
            visible_current = {
                doc_id: int(version)
                for doc_id, version in visible_query.all()
                if deny_set_allows(doc_id, authz=authz)
            }

            raw_revision_ids = []
            if (scope or {}).get("kb_revision_id"):
                raw_revision_ids.append((scope or {})["kb_revision_id"])
            raw_revision_ids.extend((scope or {}).get("kb_revision_ids") or [])
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
                allowed_revisions = {
                    doc_id: {revision} for doc_id, revision in visible_current.items()
                }

            kept = []
            for doc_id, doc_results in by_uuid.items():
                valid_revisions = allowed_revisions.get(doc_id, set())
                for result in doc_results:
                    meta = result.metadata or {}
                    raw_revision = (
                        result.document_revision
                        or meta.get("document_revision")
                        or meta.get("version")
                    )
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
            if r.get("filename"):
                meta.setdefault("filename", r["filename"])
            if r.get("title"):
                meta.setdefault("title", r["title"])
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

    @staticmethod
    def _chunks_to_dicts(chunks: List[ChunkResult]) -> List[Dict[str, Any]]:
        return [
            {
                "id": chunk.id,
                "document_id": chunk.document_id or None,
                "document_revision": chunk.document_revision,
                "text": chunk.content,
                "content": chunk.content,
                "score": chunk.score,
                "provider": chunk.provider,
                "provider_version": chunk.provider_version,
                "result_type": chunk.result_type,
                "filename": (chunk.metadata or {}).get("filename")
                or (chunk.metadata or {}).get("title"),
                "metadata": dict(chunk.metadata or {}),
            }
            for chunk in chunks
        ]


_facade: Optional[RetrievalFacade] = None


def get_retrieval_facade() -> RetrievalFacade:
    global _facade
    if _facade is None:
        from app.composition.knowledge import build_knowledge_provider_registry

        _facade = RetrievalFacade(providers=build_knowledge_provider_registry())
    return _facade
