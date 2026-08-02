"""Shared product-surface notices for API-only / incomplete packs (DD-M08/M09A)."""
from __future__ import annotations

from typing import Any, Dict

from fastapi import Response


WIKI_PRODUCT_STATUS: Dict[str, Any] = {
    "pack": "knowledge_compiler",
    "surface": "wiki",
    "status": "read_only_beta",
    "web_ui": True,
    "message": (
        "Wiki 為唯讀 Beta：/knowledge/wiki 可瀏覽與閱讀（含來源引用）；"
        "編譯與寫入仍僅限 /api/v1/wiki/*（管理員）。"
    ),
    "docs": "docs/ENCLAVE_2_0_TECHNICAL_DD.md#DD-M08",
}

GRAPH_PRODUCT_STATUS: Dict[str, Any] = {
    "pack": "knowledge_compiler",
    "surface": "graph",
    "status": "api_only_no_production_write",
    "web_ui": False,
    "production_write_path": False,
    "message": (
        "Graph 為 API-only：目前無生產寫入路徑（upsert 僅測試／eval）；"
        "正式庫實體可能為空。請勿當作完整產品功能。"
    ),
    "docs": "docs/ENCLAVE_2_0_TECHNICAL_DD.md#DD-M09A",
}


def apply_product_status_headers(response: Response, status: Dict[str, Any]) -> None:
    response.headers["X-Enclave-Product-Status"] = str(status.get("status", "unknown"))
    response.headers["X-Enclave-Product-Surface"] = str(status.get("surface", ""))
