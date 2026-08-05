"""
Phase 2 — RAGFlow HTTP Client

真實 HTTP 呼叫 RAGFlow 容器 API。
使用 httpx 非同步客戶端，支援 timeout、retry、circuit breaker。

實際 RAGFlow API 端點（v0.26.4）：
  POST /api/v1/datasets/{id}/documents      文件上傳（multipart）
  POST /api/v1/datasets/{id}/documents/parse 觸發解析
  GET  /api/v1/datasets/{id}/documents       列出文件
  POST /api/v1/retrieval                     檢索
  GET  /api/v1/system/healthz               健康檢查
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional
from uuid import UUID

import httpx

from app.core.authorization import AuthorizationContext
from app.gateway.adapters.base import BaseAdapter
from app.gateway.contracts import ChunkResult
from app.gateway.resilience import CircuitBreaker, RetryConfig
from app.gateway.service_auth import build_service_headers, make_httpx_client, build_auth_headers
from app.services.content_reference import resolve_content_bytes

logger = logging.getLogger(__name__)


class RAGFlowHTTPAdapter(BaseAdapter):
    """RAGFlow HTTP Adapter — 真實 HTTP 呼叫 RAGFlow 容器。"""

    provider = "ragflow"
    version = "1.0.0"

    def __init__(
        self,
        base_url: str = "http://localhost:9380",
        timeout: float = 120.0,
        api_key: Optional[str] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.api_key = api_key
        self._circuit = CircuitBreaker(name="ragflow", failure_threshold=3, recovery_timeout=60.0)
        self._retry_config = RetryConfig(max_retries=2, base_delay=2.0)

    def _headers(self) -> Dict[str, str]:
        return build_service_headers(self.api_key, audience="ragflow")

    async def get_dataset_config(self, dataset_id: Optional[str] = None) -> Dict[str, Any]:
        """Read the dataset's real parser settings.

        Enclave must label chunks by what RAGFlow actually ran, not by the route it
        intended, so the caller needs the upstream ``layout_recognize`` value rather
        than a hardcoded constant.
        """
        dataset_id = dataset_id or os.getenv("RAGFLOW_DATASET_ID", "")
        if not dataset_id:
            return {"status": "error", "error": "missing dataset_id"}
        try:
            async with make_httpx_client(timeout=30.0) as client:
                page = 1
                while True:
                    resp = await client.get(
                        f"{self.base_url}/api/v1/datasets?page={page}&page_size=100",
                        headers=self._headers(),
                    )
                    if resp.status_code != 200:
                        return {"status": "error", "error": f"http {resp.status_code}"}
                    batch = resp.json().get("data") or []
                    if not batch:
                        return {"status": "error", "error": "dataset not found"}
                    for ds in batch:
                        if ds.get("id") != dataset_id:
                            continue
                        parser_config = ds.get("parser_config") or {}
                        return {
                            "status": "ok",
                            "dataset_id": dataset_id,
                            "chunk_method": ds.get("chunk_method"),
                            "layout_recognize": parser_config.get("layout_recognize"),
                            "embedding_model": ds.get("embedding_model"),
                            "parser_config": parser_config,
                        }
                    page += 1
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    # ── BaseAdapter 實作 ──────────────────────────────────────────────

    async def capabilities(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "version": self.version,
            "base_url": self.base_url,
            "features": ["parse", "ocr", "layout_analysis", "table_extraction", "scan_routing", "vlm", "chunking"],
            "chunking_templates": ["general", "paper", "manual", "laws", "table", "book", "presentation", "qa"],
        }

    async def health(self) -> Dict[str, Any]:
        if not self._circuit.allow_request():
            return {"status": "unhealthy", "provider": self.provider, "error": "circuit_breaker_open"}
        try:
            async with make_httpx_client(timeout=10.0) as client:
                resp = await client.get(f"{self.base_url}/api/v1/system/healthz")
                self._circuit.record_success()
                return {
                    "status": "healthy" if resp.status_code == 200 else "unhealthy",
                    "provider": self.provider, "version": self.version,
                    "http_status": resp.status_code,
                }
        except Exception as exc:
            self._circuit.record_failure()
            return {"status": "unhealthy", "provider": self.provider, "error": str(exc)}

    async def search(
        self, authz: AuthorizationContext, query: str, top_k: int = 20,
        scope: Optional[Dict[str, Any]] = None,
    ) -> List[ChunkResult]:
        """RAGFlow 專業檢索（使用 /api/v1/retrieval）。"""
        if not self._circuit.allow_request():
            logger.warning("RAGFlow search blocked by circuit breaker")
            return []
        try:
            payload = {
                "question": query,
                "top_k": top_k,
                "tenant_id": str(authz.tenant_id),
            }
            if scope:
                payload["dataset_ids"] = scope.get("kb_ids", [])
            async with make_httpx_client(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/api/v1/retrieval",
                    json=payload, headers=self._headers(),
                )
                resp.raise_for_status()
                self._circuit.record_success()
                data = resp.json()
                return [
                    ChunkResult(
                        id=r.get("id", ""), content=r.get("content", ""),
                        score=r.get("score", 0.0), result_type="chunk",
                        document_id=r.get("document_id"), provider=self.provider,
                        provider_version=self.version,
                    )
                    for r in data.get("data", {}).get("chunks", [])
                ]
        except Exception as exc:
            self._circuit.record_failure()
            logger.error(f"RAGFlow search failed: {exc}")
            return []

    async def ingest(
        self, document_id: UUID, revision: int, content_uri: str,
        content_hash: str, file_type: str, authz: AuthorizationContext,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """提交文件到 RAGFlow dataset 並觸發解析。"""
        if not self._circuit.allow_request():
            return {"status": "error", "error": "circuit_breaker_open", "document_id": str(document_id)}

        dataset_id = (metadata or {}).get("dataset_id", "")
        if not dataset_id:
            return {"status": "error", "error": "dataset_id required in metadata", "document_id": str(document_id)}

        try:
            file_bytes = resolve_content_bytes(content_uri, metadata)
            async with make_httpx_client(timeout=self.timeout) as client:
                # Step 1: 上傳文件
                resp = await client.post(
                    f"{self.base_url}/api/v1/datasets/{dataset_id}/documents",
                    headers=build_auth_headers(self.api_key, audience="ragflow"),
                    files={"file": (f"{document_id}.{file_type}", file_bytes, "application/octet-stream")},
                )
                resp.raise_for_status()
                upload_data = resp.json()
                doc_ids = [d["id"] for d in upload_data.get("data", [])]

                # Step 2: 觸發解析
                if doc_ids:
                    parse_resp = await client.post(
                        f"{self.base_url}/api/v1/datasets/{dataset_id}/documents/parse",
                        json={"document_ids": doc_ids},
                        headers=self._headers(),
                    )
                    parse_resp.raise_for_status()

                self._circuit.record_success()
                provider_resource_id = doc_ids[0] if doc_ids else None
                return {
                    "status": "submitted",
                    "document_id": str(document_id),
                    "provider_resource_id": provider_resource_id,
                    "ragflow_doc_ids": doc_ids,
                    "provider": self.provider,
                }
        except Exception as exc:
            self._circuit.record_failure()
            logger.error(f"RAGFlow ingest failed: {exc}")
            return {"status": "error", "error": str(exc), "document_id": str(document_id)}

    async def delete(
        self, resource_type: str, resource_id: str, revision: int,
        idempotency_key: str,
    ) -> Dict[str, Any]:
        """刪除 RAGFlow 文件。"""
        try:
            async with make_httpx_client(timeout=30.0) as client:
                resp = await client.delete(
                    f"{self.base_url}/api/v1/documents/{resource_id}",
                    headers=self._headers(),
                    params={"idempotency_key": idempotency_key},
                )
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            logger.error(f"RAGFlow delete failed: {exc}")
            return {"status": "error", "error": str(exc)}

    async def reconcile(
        self, resource_type: str, resource_id: str, desired_revision: int,
    ) -> Dict[str, Any]:
        """檢查 RAGFlow 文件狀態。"""
        try:
            async with make_httpx_client(timeout=30.0) as client:
                resp = await client.get(
                    f"{self.base_url}/api/v1/documents/{resource_id}",
                    headers=self._headers(),
                )
                data = resp.json()
                current = data.get("data", {}).get("revision", 0)
                return {
                    "resource_id": resource_id, "desired_revision": desired_revision,
                    "current_revision": current, "converged": current >= desired_revision,
                }
        except Exception as exc:
            return {"resource_id": resource_id, "desired_revision": desired_revision, "converged": False, "error": str(exc)}

    # ── RAGFlow 特有方法 ──────────────────────────────────────────────

    async def parse_document(
        self, dataset_id: str, document_ids: List[str],
    ) -> Dict[str, Any]:
        """觸發文件解析。"""
        try:
            async with make_httpx_client(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/api/v1/datasets/{dataset_id}/documents/parse",
                    json={"document_ids": document_ids},
                    headers=self._headers(),
                )
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            logger.error(f"RAGFlow parse_document failed: {exc}")
            return {"status": "error", "error": str(exc)}

    async def get_parse_status(self, dataset_id: str, document_id: str) -> Dict[str, Any]:
        """取得文件解析狀態。"""
        try:
            async with make_httpx_client(timeout=30.0) as client:
                resp = await client.get(
                    f"{self.base_url}/api/v1/datasets/{dataset_id}/documents/{document_id}",
                    headers=self._headers(),
                )
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            return {"document_id": document_id, "status": "error", "error": str(exc)}

    async def get_parse_result(self, job_id: str) -> Dict[str, Any]:
        """取得解析結果（ParseArtifact 相容格式）。"""
        dataset_id = os.getenv("RAGFLOW_DATASET_ID", "")
        if not dataset_id or not job_id:
            return {
                "job_id": job_id,
                "status": "completed",
                "chunks": [],
                "warnings": ["missing dataset_id or job_id"],
                "confidence": 0.0,
            }
        try:
            async with make_httpx_client(timeout=60.0) as client:
                # 先取 doc 狀態：RAGFlow 解析期間 chunk 會增量出現，
                # 必須等 run=DONE 才能收 chunks，否則會拿到截斷的部分結果
                # （2026-08-03 盲測發現：15 頁報告只同步到 2 個表格 chunk）
                first = await client.get(
                    f"{self.base_url}/api/v1/datasets/{dataset_id}/documents/{job_id}/chunks",
                    headers=self._headers(),
                    params={"page": 1, "page_size": 100},
                )
                if first.status_code != 200:
                    return {"job_id": job_id, "status": "error", "error": first.text[:200]}
                payload = first.json()
                data = payload.get("data", {})
                if isinstance(data, list):
                    chunks_raw = data
                    doc_data = {}
                else:
                    doc_data = data.get("doc", {})
                    chunks_raw = data.get("chunks", [])
                run_status = str(doc_data.get("run", doc_data.get("status", ""))).upper()
                done = run_status in ("DONE", "3", "SUCCESS", "COMPLETED", "2")
                if not done:
                    return {
                        "job_id": job_id,
                        "status": "processing",
                        "run": run_status,
                        "chunks": [],
                        "confidence": 0.5,
                    }
                if chunks_raw:
                    # run=DONE 後分頁收齊全部 chunk（RAGFlow page_size 上限 100）
                    all_chunks = list(chunks_raw)
                    page = 2
                    while len(chunks_raw) == 100:
                        nxt = await client.get(
                            f"{self.base_url}/api/v1/datasets/{dataset_id}/documents/{job_id}/chunks",
                            headers=self._headers(),
                            params={"page": page, "page_size": 100},
                        )
                        if nxt.status_code != 200:
                            break
                        nd = nxt.json().get("data") or {}
                        chunks_raw = nd.get("chunks", []) if isinstance(nd, dict) else nd
                        if not chunks_raw:
                            break
                        all_chunks.extend(chunks_raw)
                        page += 1
                    chunks = [self._chunk_payload(c) for c in all_chunks]
                    return {
                        "job_id": job_id,
                        "status": "completed",
                        "chunks": chunks,
                        "warnings": [],
                        "confidence": 0.9,
                    }
                return {
                    "job_id": job_id,
                    "status": "completed",
                    "run": run_status,
                    "chunks": [],
                    "confidence": 0.5,
                }
        except Exception as exc:
            logger.error("RAGFlow get_parse_result failed: %s", exc)
            return {"job_id": job_id, "status": "error", "error": str(exc), "chunks": []}

    @staticmethod
    def _chunk_payload(c: dict) -> dict:
        # DeepDOC emits `positions` as [page, x1, x2, y1, y2] rows (no page_num/bbox
        # keys); derive page/bbox from the first position row so lineage survives.
        page = c.get("page_num")
        bbox = c.get("bbox")
        # RAGFlow storage layer may emit `position_int` instead of `positions`.
        positions = c.get("positions") or c.get("position_int") or []
        if page is None or bbox is None:
            rows = []
            for row in positions:
                if isinstance(row, (list, tuple)) and len(row) >= 5:
                    try:
                        rows.append((int(row[0]), float(row[1]), float(row[2]), float(row[3]), float(row[4])))
                    except (TypeError, ValueError):
                        continue
            if rows:
                if page is None:
                    page = rows[0][0]
                if bbox is None:
                    # Union of all rects on the first page so multi-rect chunks
                    # keep full coverage instead of only the first rectangle.
                    first_page = rows[0][0]
                    same_page = [r for r in rows if r[0] == first_page] or rows
                    x1 = min(r[1] for r in same_page)
                    x2 = max(r[2] for r in same_page)
                    y1 = min(r[3] for r in same_page)
                    y2 = max(r[4] for r in same_page)
                    bbox = {"x": x1, "y": y1, "w": max(0.0, x2 - x1), "h": max(0.0, y2 - y1)}
        return {
            "text": c.get("content", c.get("content_with_weight", "")),
            "template": c.get("doc_type", "general"),
            "page": page,
            "bbox": bbox,
        }

    async def export_manifest(self, kb_revision: int) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "version": self.version,
            "kb_revision": kb_revision,
            "resources": [],
        }
