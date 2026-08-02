"""
Phase 1 — Gateway Adapter Base Classes

BaseAdapter 抽象基類與 MockAdapter（測試用）。
所有下游 Adapter 必須實作 BaseAdapter 契約。
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.core.authorization import AuthorizationContext
from app.gateway.contracts import ChunkResult

logger = logging.getLogger(__name__)


class BaseAdapter(ABC):
    """Adapter 抽象基類 — 所有下游 Adapter 必須實作此介面。"""

    provider: str
    version: str

    @abstractmethod
    async def capabilities(self) -> Dict[str, Any]:
        """回傳此 Adapter 的能力清單。"""
        ...

    @abstractmethod
    async def health(self) -> Dict[str, Any]:
        """健康檢查。"""
        ...

    @abstractmethod
    async def search(
        self,
        authz: AuthorizationContext,
        query: str,
        top_k: int = 20,
        scope: Optional[Dict[str, Any]] = None,
    ) -> List[ChunkResult]:
        """執行授權檢索。"""
        ...

    @abstractmethod
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
        """擷取文件到下游。"""
        ...

    @abstractmethod
    async def delete(
        self,
        resource_type: str,
        resource_id: str,
        revision: int,
        idempotency_key: str,
    ) -> Dict[str, Any]:
        """從下游刪除資源。"""
        ...

    @abstractmethod
    async def reconcile(
        self,
        resource_type: str,
        resource_id: str,
        desired_revision: int,
    ) -> Dict[str, Any]:
        ...


    async def export_manifest(self, kb_revision: int) -> Dict[str, Any]:
        """匯出 downstream projection manifest。"""
        return {
            "provider": self.provider,
            "version": self.version,
            "kb_revision": kb_revision,
            "resources": [],
        }


class MockAdapter(BaseAdapter):
    """
    Mock Adapter — 用於 Phase 1 測試，不依賴真實下游。
    """

    provider = "mock"
    version = "0.1.0"

    def __init__(self, domain: str = "document"):
        self.domain = domain
        self._healthy = True
        self._ingested: Dict[str, Dict[str, Any]] = {}
        self._deleted: set = set()

    async def capabilities(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "version": self.version,
            "domain": self.domain,
            "features": ["search", "ingest", "delete", "reconcile"],
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
        results = []
        for i, (doc_id, doc_data) in enumerate(self._ingested.items()):
            if doc_id in self._deleted:
                continue
            results.append(ChunkResult(
                id=f"mock-{self.domain}-{i}",
                content=f"[Mock {self.domain}] Result for: {query}",
                score=0.9 - i * 0.1,
                result_type="chunk",
                document_id=doc_id,
                provider=self.provider,
                provider_version=self.version,
            ))
        return results[:top_k]

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
        doc_id_str = str(document_id)
        self._ingested[doc_id_str] = {
            "revision": revision,
            "content_hash": content_hash,
            "file_type": file_type,
            "metadata": metadata or {},
        }
        self._deleted.discard(doc_id_str)
        return {"status": "ingested", "document_id": doc_id_str, "revision": revision}

    async def delete(
        self,
        resource_type: str,
        resource_id: str,
        revision: int,
        idempotency_key: str,
    ) -> Dict[str, Any]:
        self._deleted.add(resource_id)
        return {"status": "deleted", "resource_id": resource_id, "revision": revision}

    async def reconcile(
        self,
        resource_type: str,
        resource_id: str,
        desired_revision: int,
    ) -> Dict[str, Any]:
        ingested = self._ingested.get(resource_id, {})
        current_revision = ingested.get("revision", 0)
        converged = current_revision >= desired_revision and resource_id not in self._deleted
        return {
            "resource_id": resource_id,
            "desired_revision": desired_revision,
            "current_revision": current_revision,
            "converged": converged,
        }

    def set_unhealthy(self):
        self._healthy = False

    def set_healthy(self):
        self._healthy = True
