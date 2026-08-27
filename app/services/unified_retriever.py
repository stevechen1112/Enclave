"""
Phase 5 — Unified Retrieval & Answer Generation

統一檢索聚合器：從多個 Adapter 收集結果，去重、正規化分數、單次 rerank、單次答案生成。

禁止讓三個下游各自生成答案後再拼接。
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, List, Optional, Set
from uuid import UUID

from app.core.authorization import AuthorizationContext
from app.gateway.contracts import ChunkResult, Citation, SearchDomain
from app.gateway.router import GatewayRouter

logger = logging.getLogger(__name__)


class UnifiedRetriever:
    """
    統一檢索器。

    流程：
      Authenticate → Policy Snapshot → Query Classification
      → Authorized Fan-out → Normalize Scores → Deduplicate
      → Post-authorization Validation → Rerank Once
      → Context Budget Allocation → Generate Answer Once
      → Validate Citations → Persist Trace
    """

    def __init__(self, router: GatewayRouter):
        self.router = router

    async def retrieve(
        self,
        authz: AuthorizationContext,
        query: str,
        top_k: int = 20,
        domain: SearchDomain = SearchDomain.HYBRID,
        scope: Optional[Dict[str, Any]] = None,
    ) -> UnifiedRetrievalResult:
        """
        執行統一檢索。

        Returns:
            UnifiedRetrievalResult: 去重、正規化、rerank 後的結果 + 引用
        """
        # 1. Fan-out 到 Gateway
        response = await self.router.search(
            authz=authz,
            query=query,
            domain=domain,
            top_k=top_k * 2,  # 多取一些供 rerank 使用
            scope=scope,
        )

        # 2. 正規化分數（不同 Adapter 的分數不可直接比較）
        normalized = self._normalize_scores(response.results)

        # 3. 去重（依 canonical source/revision/span）
        deduped = self._deduplicate(normalized)

        # 4. 後授權驗證（防禦性檢查）
        validated = self._post_authorize(deduped, authz)

        # 5. 取 top_k
        final_results = validated[:top_k]

        # 6. 統一 CitationBuilder（P1：禁止第二套 citation 組裝）
        from app.gateway.citation import CitationBuilder

        citations = CitationBuilder().build(
            final_results,
            acl_revision=getattr(authz, "policy_revision", 1) or 1,
        )

        return UnifiedRetrievalResult(
            results=final_results,
            citations=citations,
            audit_trail=response.audit_trail,
            total_results=len(response.results),
            deduped_count=len(deduped),
        )

    def _normalize_scores(self, results: List[ChunkResult]) -> List[ChunkResult]:
        """正規化分數到 0-1 範圍。"""
        if not results:
            return results

        scores = [r.score for r in results]
        min_s = min(scores)
        max_s = max(scores)

        if max_s == min_s:
            return results

        for r in results:
            r.score = (r.score - min_s) / (max_s - min_s)

        return sorted(results, key=lambda r: r.score, reverse=True)

    def _deduplicate(self, results: List[ChunkResult]) -> List[ChunkResult]:
        """
        去重：依 canonical source/revision/span。

        相同 document_id + 相近 chunk 內容視為重複。
        """
        seen: Set[str] = set()
        unique: List[ChunkResult] = []

        for r in results:
            # 以 content hash 的前 64 位元作為去重鍵
            content_hash = hashlib.sha256((r.content or "")[:500].encode()).hexdigest()[
                :16
            ]

            dedup_key = f"{r.document_id}:{content_hash}"
            if dedup_key not in seen:
                seen.add(dedup_key)
                unique.append(r)

        return unique

    def _post_authorize(
        self,
        results: List[ChunkResult],
        authz: AuthorizationContext,
    ) -> List[ChunkResult]:
        """後授權驗證：防禦性檢查 + deny set。"""
        from app.gateway.authorization import get_gateway_authorizer

        authorizer = get_gateway_authorizer()
        validated = []
        for r in results:
            if r.document_id and authorizer.is_denied(
                r.document_id,
                authz.subject_id,
                tenant_id=authz.tenant_id,
            ):
                continue
            validated.append(r)
        return validated

    def _build_citations(self, results: List[ChunkResult]) -> List[Citation]:
        """從檢索結果建立引用清單。"""
        citations = []
        for i, r in enumerate(results):
            citations.append(
                Citation(
                    citation_id=f"cite-{i}",
                    canonical_document_id=UUID(r.document_id)
                    if r.document_id
                    else UUID(int=0),
                    document_revision=1,
                    artifact_id=r.id,
                    artifact_type=r.result_type,
                    provider=r.provider,
                    provider_version=r.provider_version,
                    retrieval_score=r.score,
                )
            )
        return citations


class UnifiedRetrievalResult:
    """統一檢索結果。"""

    def __init__(
        self,
        results: List[ChunkResult],
        citations: List[Citation],
        audit_trail: Any,
        total_results: int = 0,
        deduped_count: int = 0,
    ):
        self.results = results
        self.citations = citations
        self.audit_trail = audit_trail
        self.total_results = total_results
        self.deduped_count = deduped_count

    def to_context_parts(self) -> List[str]:
        """將結果轉為 LLM context 片段。"""
        parts = []
        for i, r in enumerate(self.results):
            source = f"[來源 {i + 1}]"
            if r.document_id:
                source += f" (doc:{r.document_id[:8]})"
            parts.append(f"{source}\n{r.content}")
        return parts

    def to_sources_list(self) -> List[Dict[str, Any]]:
        """轉為前端可用的來源列表。"""
        return [
            {
                "id": r.id,
                "document_id": r.document_id,
                "content": r.content[:200],
                "score": r.score,
                "provider": r.provider,
                "result_type": r.result_type,
            }
            for r in self.results
        ]
