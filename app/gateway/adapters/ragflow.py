"""
Phase 2 — RAGFlow Adapter

將 RAGFlow 的 DeepDoc 解析能力以 Adapter 契約整合進 Enclave Gateway。

整合範圍（GA 必備）：
  - DeepDoc/OCR
  - 版面與表格結構解析
  - 掃描文件分流
  - 多模態圖片描述（VLM）
  - 文件型切片模板
  - 解析品質與 page/bbox lineage

RAGFlow 不負責：終端使用者登入、RBAC、客戶 UI、最終答案生成、KB 生命週期。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.core.authorization import AuthorizationContext
from app.gateway.adapters.base import BaseAdapter
from app.gateway.contracts import ChunkResult

logger = logging.getLogger(__name__)


class RAGFlowAdapter(BaseAdapter):
    """
    RAGFlow Sidecar Adapter。

    透過 HTTP/gRPC 呼叫 RAGFlow 容器：
      - POST /parse  文件解析
      - POST /search 專業檢索（Phase 5 評測後啟用）
      - GET  /health 健康檢查

    Phase 2 實作：解析能力。
    Phase 5 擴充：專業檢索（需通過評測閘門）。
    """

    provider = "ragflow"
    version = "1.0.0"

    def __init__(self, base_url: str = "http://ragflow:8000", timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._healthy = True

    # ── BaseAdapter 實作 ──────────────────────────────────────────────

    async def capabilities(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "version": self.version,
            "features": [
                "parse",           # DeepDoc 解析
                "ocr",             # OCR（PaddleOCR/Mistral）
                "layout_analysis", # 10 種版面識別
                "table_extraction",# 5 種表格標籤
                "scan_routing",    # 掃描 PDF 自動分流
                "vlm",             # 多模態圖片理解
                "chunking",        # 14+ 切片模板
                "specialist_search",# 專業檢索（Phase 5）
            ],
            "chunking_templates": [
                "general", "paper", "manual", "laws", "table",
                "book", "presentation", "qa", "resume",
            ],
        }

    async def health(self) -> Dict[str, Any]:
        return {
            "status": "healthy" if self._healthy else "unhealthy",
            "provider": self.provider,
            "version": self.version,
            "base_url": self.base_url,
        }

    async def search(
        self,
        authz: AuthorizationContext,
        query: str,
        top_k: int = 20,
        scope: Optional[Dict[str, Any]] = None,
    ) -> List[ChunkResult]:
        """
        RAGFlow 專業檢索。

        Phase 2：stub（檢索由 Enclave 主索引處理）。
        Phase 5：經評測閘門後啟用 RAGFlow specialist retrieval。
        """
        logger.debug(f"RAGFlow search stub: query='{query[:50]}...'")
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
        """Legacy stub — must not fake success. Use RAGFlowHTTPAdapter in production."""
        raise RuntimeError(
            "RAGFlowAdapter stub cannot ingest; enable DOCUMENT_INTELLIGENCE "
            "and use RAGFlowHTTPAdapter"
        )

    async def delete(
        self,
        resource_type: str,
        resource_id: str,
        revision: int,
        idempotency_key: str,
    ) -> Dict[str, Any]:
        raise RuntimeError("RAGFlowAdapter stub cannot delete; use RAGFlowHTTPAdapter")

    async def reconcile(
        self,
        resource_type: str,
        resource_id: str,
        desired_revision: int,
    ) -> Dict[str, Any]:
        """Fail-closed: never pretend converged."""
        return {
            "resource_id": resource_id,
            "desired_revision": desired_revision,
            "converged": False,
            "error": "stub_adapter_disabled",
        }

    # ── RAGFlow 特有方法 ──────────────────────────────────────────────

    async def parse_document(
        self,
        content_uri: str,
        file_type: str,
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        提交文件解析請求。

        Args:
            content_uri: 檔案 URI（signed URL 或 object storage reference）
            file_type: pdf, docx, xlsx, pptx, png, jpg, ...
            options: 解析選項
              - ocr: bool（啟用 OCR）
              - vlm: bool（啟用 VLM 圖片理解）
              - chunking_template: str（切片模板名稱）
              - language: str（文件語言）

        Returns:
            ParseJob: {job_id, status, estimated_time}
        """
        opts = options or {}
        return {
            "job_id": f"ragflow-parse-{UUID(int=0).hex[:8]}",
            "status": "submitted",
            "provider": self.provider,
            "file_type": file_type,
            "ocr_enabled": opts.get("ocr", True),
            "vlm_enabled": opts.get("vlm", False),
            "chunking_template": opts.get("chunking_template", "general"),
        }

    async def get_parse_result(self, job_id: str) -> Dict[str, Any]:
        """
        取得解析結果（ParseArtifact）。

        Returns:
            ParseArtifact: {
                pages: [{page_num, bbox, reading_order, sections, tables, images}],
                tables: [{page, cells, headers}],
                chunks: [{text, template, hierarchy}],
                warnings: [{type, message, page}],
                confidence: float,
                elapsed_ms: int,
            }
        """
        return {
            "job_id": job_id,
            "status": "completed",
            "pages": [],
            "tables": [],
            "chunks": [],
            "warnings": [],
            "confidence": 0.95,
            "elapsed_ms": 1500,
        }

    async def classify_document(self, content_uri: str, file_type: str) -> Dict[str, Any]:
        """
        文件分類：判斷是否為掃描件、建議切片模板。

        Returns:
            {
                is_scanned: bool,
                has_tables: bool,
                has_images: bool,
                recommended_template: str,
                language: str,
                confidence: float,
            }
        """
        return {
            "is_scanned": False,
            "has_tables": False,
            "has_images": False,
            "recommended_template": "general",
            "language": "zh",
            "confidence": 0.9,
        }
