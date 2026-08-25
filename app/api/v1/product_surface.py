"""Shared product-surface notices for API-only / incomplete packs (DD-M08/M09A)."""
from __future__ import annotations

from typing import Any, Dict

from fastapi import Response


WIKI_PRODUCT_STATUS: Dict[str, Any] = {
    "pack": "knowledge_compiler",
    "surface": "wiki",
    "status": "beta",
    "web_ui": True,
    "message": (
        "Wiki 為 Beta：/knowledge/wiki 可瀏覽與閱讀（含來源引用）；"
        "管理員可於閱讀頁手動編輯（新增 revision，不覆寫歷史）；"
        "編譯仍由 WeKnora 觸發（/api/v1/wiki/compile，管理員）。"
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


def with_runtime_status(status: Dict[str, Any]) -> Dict[str, Any]:
    """Overlay startup/operator probe truth without mutating static metadata."""
    result = dict(status)
    surface = str(result.get("surface") or "")
    from app.gateway.runtime_health import get_runtime_health_snapshot

    snapshot = get_runtime_health_snapshot() or {}
    adapter = (snapshot.get("adapters") or {}).get(surface) or {}
    runtime_state = str(adapter.get("status") or "unavailable")
    available = bool(adapter.get("available", False))
    result["runtime_state"] = runtime_state
    result["available"] = available
    if not available:
        result["status"] = "runtime_unavailable"
        result["message"] = (
            "此能力已設定，但執行服務目前未通過健康探測；核心文件問答仍可使用。"
        )
    return result
