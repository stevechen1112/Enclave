"""Phase 2 — Document parse capability router."""
from __future__ import annotations

import os
from enum import Enum
from typing import Optional


class ParseRoute(str, Enum):
    NATIVE_FAST = "native_fast"
    NATIVE_STRUCTURED = "native_structured"
    RAGFLOW_DEEPDOC = "ragflow_deepdoc"
    RAGFLOW_VLM = "ragflow_vlm"


def classify_document(file_path: str, file_type: str) -> ParseRoute:
    """Route documents to appropriate parser based on type and heuristics."""
    canary = os.getenv("PARSER_CANARY", "").lower().strip()
    # A/B：native | ragflow — 強制整批路由（可回滾）
    if canary == "native":
        return _native_route(file_type)
    if canary == "ragflow" and _ragflow_enabled():
        return _ragflow_route(file_type)

    # Pilot / eval：強制所有可解析文件走 RAGFlow（禁止 native 冒充 PASS）
    if os.getenv("RAGFLOW_FORCE_PARSE", "").lower() == "true" and _ragflow_enabled():
        return _ragflow_route(file_type)

    ext = (file_type or "").lower().strip()
    if ext in {"csv", "xlsx", "xls", "json"}:
        return ParseRoute.NATIVE_STRUCTURED
    if ext in {"png", "jpg", "jpeg", "gif", "webp", "tiff"}:
        return ParseRoute.RAGFLOW_VLM if _ragflow_enabled() else ParseRoute.NATIVE_FAST
    if ext in {"pdf"}:
        size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
        if size > 5 * 1024 * 1024:
            return ParseRoute.RAGFLOW_DEEPDOC if _ragflow_enabled() else ParseRoute.NATIVE_FAST
        return ParseRoute.NATIVE_FAST if not _ragflow_enabled() else ParseRoute.RAGFLOW_DEEPDOC
    if ext in {"docx", "doc", "pptx", "ppt", "html", "md", "txt"}:
        return ParseRoute.NATIVE_FAST
    return ParseRoute.NATIVE_FAST


def _native_route(file_type: str) -> ParseRoute:
    ext = (file_type or "").lower().strip()
    if ext in {"csv", "xlsx", "xls", "json"}:
        return ParseRoute.NATIVE_STRUCTURED
    return ParseRoute.NATIVE_FAST


def _ragflow_route(file_type: str) -> ParseRoute:
    ext = (file_type or "").lower().strip()
    if ext in {"png", "jpg", "jpeg", "gif", "webp", "tiff"}:
        return ParseRoute.RAGFLOW_VLM
    if ext in {"csv", "xlsx", "xls"}:
        return ParseRoute.NATIVE_STRUCTURED
    return ParseRoute.RAGFLOW_DEEPDOC


def _ragflow_enabled() -> bool:
    return os.getenv("RAGFLOW_ENABLED", "").lower() == "true"
