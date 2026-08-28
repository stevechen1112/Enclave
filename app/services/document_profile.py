"""Deterministic document capability profiling.

Processing success and answer readiness are deliberately separate states.
Unsupported or low-quality inputs remain visible with actionable warnings.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

PROFILER_VERSION = "1.1"

FORMAT_CAPABILITIES = {
    "txt": "supported",
    "md": "supported",
    "markdown": "supported",
    "csv": "supported",
    "xlsx": "supported",
    "xls": "supported",
    "docx": "supported",
    "doc": "supported",
    "pdf_text": "supported",
    "pdf_scan": "limited",
    "html": "supported",
    "rtf": "supported",
    "json": "supported",
    "pptx": "limited",
    "ppt": "limited",
    "image": "experimental",
    "audio": "experimental",
    "handwriting": "unsupported",
    "cad": "unsupported",
    "unknown": "unsupported",
}


@dataclass(frozen=True)
class ProfileResult:
    format_family: str
    support_level: str
    language_profile: dict[str, Any]
    structure_map: dict[str, Any]
    readiness: dict[str, bool]
    warnings: list[dict[str, str]] = field(default_factory=list)
    answer_ready: bool = False
    quality_score: float | None = None
    profiler_version: str = PROFILER_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def detect_language(text: str) -> dict[str, Any]:
    text = text or ""
    zh = len(re.findall(r"[\u3400-\u9fff]", text))
    en = len(re.findall(r"[A-Za-z]", text))
    codes = len(re.findall(r"\b[A-Z]{1,5}[-_/]?\d{2,}\b", text))
    if zh and en:
        primary = "zh-Hant+en"
    elif zh:
        primary = "zh-Hant"
    elif en:
        primary = "en"
    else:
        primary = "und"
    return {"primary": primary, "zh_chars": zh, "latin_chars": en, "code_tokens": codes}


def build_document_profile(
    *,
    file_type: str,
    text: str,
    parse_engine: str = "",
    ocr_used: bool = False,
    page_count: int | None = None,
    parse_status: str = "completed",
    quality_report: dict[str, Any] | None = None,
) -> ProfileResult:
    ext = (file_type or "").lower().lstrip(".")
    if ext == "pdf":
        family = "pdf_scan" if ocr_used else "pdf_text"
    elif ext in {"png", "jpg", "jpeg", "tiff", "webp"}:
        family = "image"
    elif ext in {"wav", "mp3", "m4a", "ogg", "webm"}:
        family = "audio"
    else:
        family = ext if ext in FORMAT_CAPABILITIES else "unknown"
    support = FORMAT_CAPABILITIES[family]
    q = quality_report or {}
    warnings: list[dict[str, str]] = []
    if parse_status not in {"completed", "ready"}:
        warnings.append(
            {"code": "processing_incomplete", "action": "修復解析錯誤後重新匯入"}
        )
    if not (text or "").strip():
        warnings.append(
            {"code": "empty_content", "action": "檢查來源檔或啟用 OCR／語音轉錄"}
        )
    if family == "pdf_scan" and parse_engine in {"native", "text_fallback", ""}:
        warnings.append(
            {
                "code": "scan_without_verified_ocr",
                "action": "使用 OCR 重新解析並抽查頁面",
            }
        )
    if support in {"limited", "experimental", "unsupported"}:
        warnings.append(
            {"code": f"format_{support}", "action": "人工抽查後再納入正式知識版本"}
        )
    score = q.get("score")
    has_text = bool((text or "").strip())
    process_ok = parse_status in {"completed", "ready"}
    narrative = (
        process_ok
        and has_text
        and support != "unsupported"
        and not any(w["code"] == "scan_without_verified_ocr" for w in warnings)
    )
    table_markers = bool(re.search(r"\|.+\||\t|,{2,}", text or "")) or ext in {
        "csv",
        "xls",
        "xlsx",
    }
    procedure_markers = bool(
        re.search(
            r"(?:步驟|流程|首先|接著|完成條件|Step\s*\d)", text or "", re.IGNORECASE
        )
    )
    readiness = {
        "catalog": process_ok,
        "narrative": narrative,
        "structured_rows": narrative and table_markers,
        "procedure": narrative and procedure_markers,
        "entity": narrative,
        "compiled": False,
        "voice_transcript": family == "audio" and narrative,
    }
    structure = {
        "pages": page_count,
        "has_table_markers": table_markers,
        "has_procedure_markers": procedure_markers,
        "sections": len(re.findall(r"(?m)^#{1,6}\s+|^第.+[章節]", text or "")),
    }
    return ProfileResult(
        family,
        support,
        detect_language(text),
        structure,
        readiness,
        warnings,
        answer_ready=narrative,
        quality_score=float(score) if score is not None else None,
    )


def upsert_document_profile(
    db, document, text: str, metadata: dict[str, Any] | None = None
):
    """Persist the capability profile in the caller's processing transaction."""
    from app.models.knowledge_engine import DocumentProfile

    meta = metadata or {}
    revision = int(getattr(document, "version", None) or 1)
    profile = build_document_profile(
        file_type=getattr(document, "file_type", "") or "",
        text=text,
        parse_engine=str(meta.get("parse_engine") or ""),
        ocr_used=bool(meta.get("ocr_used")),
        page_count=meta.get("page_count") or meta.get("pages"),
        parse_status="completed",
        quality_report=meta,
    )
    row = (
        db.query(DocumentProfile)
        .filter(
            DocumentProfile.document_id == document.id,
            DocumentProfile.document_revision == revision,
        )
        .first()
    )
    values = {
        "tenant_id": document.tenant_id,
        "document_id": document.id,
        "document_revision": revision,
        "format_family": profile.format_family,
        "support_level": profile.support_level,
        "language_profile": profile.language_profile,
        "page_count": meta.get("page_count") or meta.get("pages"),
        "structure_map": profile.structure_map,
        "capability_readiness": profile.readiness,
        "warnings": profile.warnings,
        "quality_score": profile.quality_score,
        "answer_ready": profile.answer_ready,
        "profiler_version": profile.profiler_version,
        "content_hash": str(
            getattr(document, "content_hash", "")
            or meta.get("content_hash")
            or "unknown"
        ),
    }
    if row is None:
        row = DocumentProfile(**values)
        db.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    db.flush()
    return row
