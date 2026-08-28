"""
Phase 1 — Enclave Canonical Adapter

Primary retrieval against Enclave pgvector index (canonical data plane).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

from app.core.authorization import AuthorizationContext
from app.gateway.adapters.base import BaseAdapter
from app.gateway.contracts import ChunkResult

logger = logging.getLogger(__name__)


class EnclaveCanonicalAdapter(BaseAdapter):
    """Search and projection against Enclave canonical store."""

    provider = "enclave"
    version = "1.0.0"

    def __init__(self):
        self._retriever = None

    def _get_retriever(self):
        if self._retriever is None:
            from app.services.kb_retrieval import KnowledgeBaseRetriever

            self._retriever = KnowledgeBaseRetriever()
        return self._retriever

    async def capabilities(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "version": self.version,
            "features": ["search", "ingest", "delete", "reconcile"],
            "index": "pgvector",
        }

    async def health(self) -> dict[str, Any]:
        def probe_database() -> None:
            from sqlalchemy import text

            from app.db.session import SessionLocal

            db = SessionLocal()
            try:
                db.execute(text("SELECT 1"))
            finally:
                db.close()

        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, probe_database)
            return {
                "status": "healthy",
                "provider": self.provider,
                "version": self.version,
            }
        except Exception as exc:  # noqa: BLE001 - health probes must report all failures
            return {
                "status": "unhealthy",
                "provider": self.provider,
                "version": self.version,
                "error": str(exc),
            }

    async def search(
        self,
        authz: AuthorizationContext,
        query: str,
        top_k: int = 20,
        scope: dict[str, Any] | None = None,
    ) -> list[ChunkResult]:
        retriever = self._get_retriever()
        loop = asyncio.get_event_loop()
        raw = await loop.run_in_executor(
            None,
            lambda: retriever.search(
                tenant_id=authz.tenant_id,
                query=query,
                top_k=top_k,
                mode="hybrid",
                authz=authz,
                filter_dict=scope,
            ),
        )
        results: list[ChunkResult] = []
        for item in raw:
            results.append(
                ChunkResult(
                    id=str(item.get("id", "")),
                    content=item.get("content", ""),
                    score=float(item.get("score", 0)),
                    result_type="chunk",
                    document_id=item.get("document_id"),
                    document_revision=item.get("document_revision"),
                    provider=self.provider,
                    provider_version=self.version,
                    metadata={
                        "filename": item.get("filename", ""),
                        "chunk_index": item.get("chunk_index"),
                        "document_revision": item.get("document_revision"),
                        "source": item.get("source", "hybrid"),
                    },
                )
            )
        return results

    async def ingest(
        self,
        document_id: UUID,
        revision: int,
        content_uri: str,
        content_hash: str,
        file_type: str,
        authz: AuthorizationContext,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "status": "indexed",
            "document_id": str(document_id),
            "revision": revision,
            "provider": self.provider,
        }

    async def delete(
        self,
        resource_type: str,
        resource_id: str,
        revision: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return {
            "status": "tombstoned",
            "resource_id": resource_id,
            "revision": revision,
            "provider": self.provider,
        }

    async def reconcile(
        self,
        resource_type: str,
        resource_id: str,
        desired_revision: int,
    ) -> dict[str, Any]:
        return {
            "resource_id": resource_id,
            "desired_revision": desired_revision,
            "current_revision": desired_revision,
            "converged": True,
            "provider": self.provider,
        }

    async def export_manifest(self, kb_revision: int) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "version": self.version,
            "kb_revision": kb_revision,
            "resources": [],
        }
