"""
Phase 4 — WeKnora HTTP Client

真實 HTTP 呼叫 WeKnora 容器 API。
支援 Auto-Wiki 編譯、GraphRAG 查詢、父文檔檢索。

實際 WeKnora API 端點：
  POST /api/v1/auth/login                    登入
  GET  /api/v1/knowledge-bases               列出 KB
  POST /api/v1/knowledge-bases               建立 KB
  POST /api/v1/knowledge-bases/{id}/knowledge/file  文件上傳
  GET  /api/v1/knowledge/search              全域搜尋
  POST /api/v1/knowledgebase/{id}/wiki/rebuild-links  Wiki 重建
  GET  /api/v1/knowledgebase/{id}/wiki/pages/{slug}   Wiki 頁面
  GET  /health                               健康檢查
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional
from uuid import UUID

import httpx

from app.gateway.service_auth import build_service_headers, make_httpx_client, build_auth_headers
from app.services.content_reference import resolve_content_bytes
from app.core.authorization import AuthorizationContext
from app.gateway.adapters.base import BaseAdapter
from app.gateway.contracts import ChunkResult, SidecarAuthError
from app.gateway.resilience import CircuitBreaker

logger = logging.getLogger(__name__)


class WeKnoraHTTPAdapter(BaseAdapter):
    """WeKnora HTTP Adapter — 真實 HTTP 呼叫 WeKnora 容器。"""

    provider = "weknora"
    version = "1.0.0"

    def __init__(
        self, base_url: str = "http://weknora:8080",
        timeout: float = 120.0, api_key: Optional[str] = None,
        token_provider=None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.api_key = api_key
        # A3: token provider owns the credential and auto-refreshes the 24h JWT.
        self._token_provider = token_provider
        self._circuit = CircuitBreaker(name="weknora", failure_threshold=3, recovery_timeout=60.0)

    async def _resolve_api_key(self) -> Optional[str]:
        if self._token_provider is not None:
            return await self._token_provider.get_token()
        return self.api_key

    def _apply_credential(self, headers: Dict[str, str], key: Optional[str]) -> Dict[str, str]:
        # A4: a long-lived sk- tenant API key authenticates via the X-API-Key
        # channel, not Bearer JWT. Sending it as Bearer would 401.
        if key and key.startswith("sk-"):
            headers.pop("Authorization", None)
            headers["X-API-Key"] = key
        return headers

    async def _headers(self) -> Dict[str, str]:
        key = await self._resolve_api_key()
        return self._apply_credential(build_service_headers(key, audience="weknora"), key)

    async def _auth_headers(self) -> Dict[str, str]:
        key = await self._resolve_api_key()
        return self._apply_credential(build_auth_headers(key, audience="weknora"), key)

    # ── BaseAdapter 實作 ──────────────────────────────────────────────

    async def capabilities(self) -> Dict[str, Any]:
        return {
            "provider": self.provider, "version": self.version,
            "base_url": self.base_url,
            "features": ["auto_wiki", "graph_rag", "parent_child_retrieval",
                         "cross_reference", "contradiction_detection", "wiki_revision"],
            "wiki_page_types": ["summary", "entity", "concept", "index", "synthesis", "comparison"],
        }

    async def health(self) -> Dict[str, Any]:
        if not self._circuit.allow_request():
            return {"status": "unhealthy", "provider": self.provider, "error": "circuit_breaker_open"}
        try:
            async with make_httpx_client(timeout=10.0) as client:
                resp = await client.get(f"{self.base_url}/health")
                self._circuit.record_success()
                return {
                    "status": "healthy" if resp.status_code == 200 else "unhealthy",
                    "provider": self.provider, "http_status": resp.status_code,
                }
        except Exception as exc:
            self._circuit.record_failure()
            return {"status": "unhealthy", "provider": self.provider, "error": str(exc)}

    def _search_kb_ids(self, scope: Optional[Dict[str, Any]]) -> List[str]:
        """KB scope for the search: explicit scope wins, else the configured default KB."""
        kb_ids = list((scope or {}).get("knowledge_base_ids") or [])
        if not kb_ids:
            default_kb = os.getenv("WEKNORA_KB_ID", "")
            if default_kb:
                kb_ids = [default_kb]
        return kb_ids

    async def search(
        self, authz: AuthorizationContext, query: str, top_k: int = 20,
        scope: Optional[Dict[str, Any]] = None,
    ) -> List[ChunkResult]:
        """Wiki/Graph 檢索（D1：改用正確的 POST /knowledge-search）。"""
        if not self._circuit.allow_request():
            logger.warning("WeKnora search blocked by circuit breaker")
            return []
        kb_ids = self._search_kb_ids(scope)
        if not kb_ids:
            logger.warning("WeKnora search skipped: no knowledge_base_ids "
                           "(set WEKNORA_KB_ID or pass scope.knowledge_base_ids)")
            return []
        try:
            async with make_httpx_client(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/api/v1/knowledge-search",
                    json={"query": query, "knowledge_base_ids": kb_ids},
                    headers=await self._headers(),
                )
                # A5 fail-closed: 401/403 must surface, not masquerade as "no results".
                if resp.status_code in (401, 403):
                    self._circuit.record_failure()
                    logger.error("WeKnora search auth failed: http %s", resp.status_code)
                    raise SidecarAuthError(self.provider, resp.status_code, resp.text[:200])
                resp.raise_for_status()
                self._circuit.record_success()
                data = resp.json()
                items = data.get("data") or []
                results: List[ChunkResult] = []
                for r in items[:top_k]:
                    results.append(
                        ChunkResult(
                            id=str(r.get("id") or r.get("chunk_id") or ""),
                            content=str(r.get("content") or ""),
                            score=float(r.get("score", 0.0)),
                            result_type=str(r.get("source_type") or "knowledge_chunk"),
                            document_id=(r.get("knowledge_id") or None),
                            provider=self.provider,
                            provider_version=self.version,
                            metadata={
                                "knowledge_base_id": r.get("knowledge_base_id"),
                                "chunk_id": r.get("chunk_id"),
                                "match_type": r.get("match_type"),
                            },
                        )
                    )
                return results
        except SidecarAuthError:
            raise
        except Exception as exc:
            self._circuit.record_failure()
            logger.error(f"WeKnora search failed: {exc}")
            return []

    async def ingest(
        self, document_id: UUID, revision: int, content_uri: str,
        content_hash: str, file_type: str, authz: AuthorizationContext,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """提交文件到 WeKnora KB。"""
        if not self._circuit.allow_request():
            return {"status": "error", "error": "circuit_breaker_open", "document_id": str(document_id)}

        kb_id = (metadata or {}).get("kb_id", "")
        if not kb_id:
            return {"status": "error", "error": "kb_id required in metadata", "document_id": str(document_id)}

        try:
            file_bytes = resolve_content_bytes(content_uri, metadata)
            async with make_httpx_client(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/api/v1/knowledge-bases/{kb_id}/knowledge/file",
                    headers=await self._auth_headers(),
                    files={"file": (f"{document_id}.{file_type}", file_bytes, "application/octet-stream")},
                )
                resp.raise_for_status()
                self._circuit.record_success()
                return resp.json()
        except Exception as exc:
            self._circuit.record_failure()
            logger.error(f"WeKnora ingest failed: {exc}")
            return {"status": "error", "error": str(exc), "document_id": str(document_id)}

    async def delete(
        self, resource_type: str, resource_id: str, revision: int,
        idempotency_key: str,
    ) -> Dict[str, Any]:
        """刪除 WeKnora 資源。"""
        try:
            async with make_httpx_client(timeout=30.0) as client:
                resp = await client.delete(
                    f"{self.base_url}/api/v1/knowledge/{resource_id}",
                    headers=await self._headers(),
                    params={"idempotency_key": idempotency_key},
                )
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    async def reconcile(
        self, resource_type: str, resource_id: str, desired_revision: int,
    ) -> Dict[str, Any]:
        """向 WeKnora 查詢資源版本是否收斂；失敗時不得假裝 converged。"""
        try:
            async with make_httpx_client(timeout=30.0) as client:
                resp = await client.get(
                    f"{self.base_url}/api/v1/knowledge/{resource_id}",
                    headers=await self._headers(),
                )
                if resp.status_code == 404:
                    return {
                        "resource_id": resource_id,
                        "desired_revision": desired_revision,
                        "converged": desired_revision == 0,
                        "state": "missing",
                    }
                if resp.status_code != 200:
                    return {
                        "resource_id": resource_id,
                        "desired_revision": desired_revision,
                        "converged": False,
                        "error": f"http_{resp.status_code}",
                    }
                data = resp.json().get("data", resp.json())
                applied = int(data.get("revision", data.get("version", -1)))
                return {
                    "resource_id": resource_id,
                    "desired_revision": desired_revision,
                    "applied_revision": applied,
                    "converged": applied == desired_revision,
                }
        except Exception as exc:
            return {
                "resource_id": resource_id,
                "desired_revision": desired_revision,
                "converged": False,
                "error": str(exc),
            }

    # ── WeKnora 特有 ──────────────────────────────────────────────────

    async def compile_wiki(self, kb_id: UUID) -> Dict[str, Any]:
        """觸發 Wiki 連結重建。"""
        try:
            async with make_httpx_client(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/api/v1/knowledgebase/{kb_id}/wiki/rebuild-links",
                    headers=await self._headers(),
                )
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            return {"kb_id": str(kb_id), "status": "error", "error": str(exc)}

    async def get_wiki_page(self, kb_id: UUID, page_slug: str) -> Optional[Dict[str, Any]]:
        """取得 Wiki 頁面。"""
        try:
            async with make_httpx_client(timeout=30.0) as client:
                resp = await client.get(
                    f"{self.base_url}/api/v1/knowledgebase/{kb_id}/wiki/pages/{page_slug}",
                    headers=await self._headers(),
                )
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            logger.error(f"WeKnora get_wiki_page failed: {exc}")
            return None

    async def list_wiki_pages(self, kb_id: UUID) -> List[Dict[str, Any]]:
        """列出 Wiki 頁面。"""
        try:
            async with make_httpx_client(timeout=30.0) as client:
                resp = await client.get(
                    f"{self.base_url}/api/v1/knowledgebase/{kb_id}/wiki/pages",
                    headers=await self._headers(),
                )
                resp.raise_for_status()
                payload = resp.json()
                return payload.get("data") or payload.get("pages") or []
        except Exception as exc:
            logger.error(f"WeKnora list_wiki_pages failed: {exc}")
            return []
