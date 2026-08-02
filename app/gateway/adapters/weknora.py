"""
Phase 4 — WeKnora Adapter

將 WeKnora 的 Auto-Wiki 知識編譯、GraphRAG、父文檔檢索以 Adapter 契約整合。

整合範圍：
  - Auto-Wiki 持續知識編譯（6 種頁面類型）
  - [[slug]] 交叉引用與 backlink
  - 父子分塊／父文檔檢索
  - 知識圖與關係查詢（GraphRAG）
  - stale/contradiction/missing-information 維護工作流
  - Wiki 修訂、人工審核、發布與回滾

WeKnora 不負責：終端身分、RBAC、客戶 UI、最終資料保留政策。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.core.authorization import AuthorizationContext
from app.gateway.adapters.base import BaseAdapter
from app.gateway.contracts import ChunkResult

logger = logging.getLogger(__name__)


class WeKnoraAdapter(BaseAdapter):
    """
    WeKnora Sidecar Adapter。

    透過 HTTP/gRPC 呼叫 WeKnora 容器。
    """

    provider = "weknora"
    version = "1.0.0"

    def __init__(self, base_url: str = "http://weknora:8000", timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._healthy = True

    # ── BaseAdapter 實作 ──────────────────────────────────────────────

    async def capabilities(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "version": self.version,
            "features": [
                "auto_wiki", "graph_rag", "parent_child_retrieval",
                "cross_reference", "contradiction_detection", "wiki_revision",
            ],
            "wiki_page_types": [
                "summary", "entity", "concept", "index", "synthesis", "comparison",
            ],
        }

    async def health(self) -> Dict[str, Any]:
        return {
            "status": "healthy" if self._healthy else "unhealthy",
            "provider": self.provider,
            "version": self.version,
        }

    async def search(
        self,
        authz: AuthorizationContext,
        query: str,
        top_k: int = 20,
        scope: Optional[Dict[str, Any]] = None,
    ) -> List[ChunkResult]:
        """Wiki/Graph 檢索。"""
        logger.debug(f"WeKnora search: query='{query[:50]}...'")
        return []

    async def ingest(
        self,
        document_id: UUID,
        revision: int,
        content_uri: str,
        content_hash: str,
        file_type: str,
        authz: AuthorizationContext,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        raise RuntimeError(
            "WeKnoraAdapter stub cannot ingest; enable KNOWLEDGE_COMPILER "
            "and use WeKnoraHTTPAdapter"
        )

    async def delete(
        self,
        resource_type: str,
        resource_id: str,
        revision: int,
        idempotency_key: str,
    ) -> Dict[str, Any]:
        raise RuntimeError("WeKnoraAdapter stub cannot delete; use WeKnoraHTTPAdapter")

    async def reconcile(
        self,
        resource_type: str,
        resource_id: str,
        desired_revision: int,
    ) -> Dict[str, Any]:
        return {
            "resource_id": resource_id,
            "desired_revision": desired_revision,
            "converged": False,
            "error": "stub_adapter_disabled",
        }

    # ── WeKnora 特有方法 ──────────────────────────────────────────────

    async def compile_wiki(self, kb_id: UUID, document_ids: List[UUID]) -> Dict[str, Any]:
        """觸發 Wiki 編譯。"""
        return {"kb_id": str(kb_id), "status": "compile_started", "document_count": len(document_ids)}

    async def get_wiki_page(self, page_slug: str) -> Optional[Dict[str, Any]]:
        """取得 Wiki 頁面。"""
        return None

    async def list_wiki_pages(self, kb_id: UUID) -> List[Dict[str, Any]]:
        """列出 KB 的所有 Wiki 頁面。"""
        return []

    async def search_graph(self, query: str, authz: AuthorizationContext) -> List[Dict[str, Any]]:
        """GraphRAG 關係查詢。"""
        return []

    async def get_parent_document(self, chunk_id: str) -> Optional[Dict[str, Any]]:
        """父文檔檢索：從子 chunk 取得父文檔。"""
        return None
