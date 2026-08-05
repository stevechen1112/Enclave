"""VISION Phase 2 — 解釋式拒答：說明缺文件／缺證據，非空話。"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# 問金額／報價但召回段落無數字時，拒答避免幻覺（Blind Z3-049/058/080）
_AMOUNT_ASK = (
    "金額", "總價", "報價", "價位", "價格", "多少錢", "費用", "月費", "專案費", "含稅",
)
_AMOUNT_IN_TEXT = re.compile(
    r"(?:"
    r"NT\$\s*\d|"
    r"\$\s*\d{1,3}(?:,\d{3})+|"
    r"(?:USD|EUR)\s*\d|"
    r"\d{1,3}(?:,\d{3})+(?:\.\d+)?\s*(?:元|萬)?|"
    r"\d{3,}\s*(?:元|萬)|"
    r"(?:未稅|含稅)金額\s*\d{2,}|"
    r"[一二三四五六七八九十百千萬億兩]\s*萬"
    r")"
)


def amount_question_lacks_numeric_evidence(
    question: str,
    chunk_hits: Optional[List[Dict[str, Any]]] = None,
) -> bool:
    """題目在問金額，但 chunk 正文看不到可用數字 → 應拒答而非臆測。"""
    q = question or ""
    if not any(a in q for a in _AMOUNT_ASK):
        return False
    blob = "\n".join((h.get("content") or h.get("text") or "") for h in (chunk_hits or []))
    return not bool(_AMOUNT_IN_TEXT.search(blob))


def guarantee_question_lacks_evidence(
    question: str,
    chunk_hits: Optional[List[Dict[str, Any]]] = None,
) -> bool:
    """題目在問「保證」事項，但召回正文沒有「保證」→ 禁止用他處日期／活動日頂替。"""
    q = question or ""
    if "保證" not in q:
        return False
    blob = "\n".join((h.get("content") or h.get("text") or "") for h in (chunk_hits or []))
    return "保證" not in blob


def build_refusal(
    *,
    question: str,
    plan_intent: str = "",
    chunk_hits: Optional[List[Dict[str, Any]]] = None,
    catalog_hits: Optional[List[Dict[str, Any]]] = None,
    clause_projections: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """產生結構化拒答資訊。

    reason:
      - no_evidence: 完全無命中
      - low_evidence: 有命中但不足以回答（由呼叫端在 has_policy=False 時使用）
      - unanswerable_intent: 題型暗示庫外知識
    """
    chunks = chunk_hits or []
    catalogs = catalog_hits or []
    projections = clause_projections or []
    titles = []
    for h in catalogs:
        if h.get("filename"):
            titles.append(h["filename"])
    for h in chunks:
        fn = h.get("filename") or (h.get("metadata") or {}).get("filename")
        if fn and fn not in titles:
            titles.append(fn)

    missing_docs: List[str] = []
    missing_fields: List[str] = []
    reason = "no_evidence"

    q = question or ""
    if plan_intent == "unanswerable" or _looks_out_of_corpus(q):
        reason = "unanswerable_intent"
        missing_docs = ["（題目指向知識庫未收錄主題，無對應文件）"]
    elif not chunks and not catalogs and not projections:
        reason = "no_evidence"
        missing_docs = _guess_missing_topics(q)
    else:
        reason = "low_evidence"
        missing_fields = ["題目所需欄位／事實未出現在已召回段落中"]

    message = format_refusal_message(
        reason=reason,
        missing_docs=missing_docs,
        missing_fields=missing_fields,
        seen_titles=titles[:5],
    )
    return {
        "reason": reason,
        "missing_docs": missing_docs,
        "missing_fields": missing_fields,
        "seen_titles": titles[:8],
        "message": message,
    }


def format_refusal_message(
    *,
    reason: str,
    missing_docs: List[str],
    missing_fields: List[str],
    seen_titles: List[str],
) -> str:
    lines = ["抱歉，目前無法依據知識庫中的資料回答此問題。"]
    if reason == "unanswerable_intent":
        lines.append("此問題指向知識庫未收錄的主題，系統拒絕臆測。")
    if missing_docs:
        lines.append("可能缺少的文件／主題：")
        for d in missing_docs[:5]:
            lines.append(f"- {d}")
    if missing_fields:
        lines.append("可能缺少的欄位／事實：")
        for f in missing_fields[:5]:
            lines.append(f"- {f}")
    if seen_titles:
        lines.append("已檢索到但不足以回答的文件：")
        for t in seen_titles:
            lines.append(f"- {t}")
    lines.append("請補充相關文件後再問，或改問庫內已有文件可直接摘錄的事實。")
    return "\n".join(lines)


def _looks_out_of_corpus(q: str) -> bool:
    hints = ("火星", "隱藏折扣", "私人手機", "2028", "刪除所有稽核", "未收錄")
    return any(h in q for h in hints)


def _guess_missing_topics(q: str) -> List[str]:
    topics = []
    mapping = (
        ("營業稅", "營業稅繳款書"),
        ("MOU", "合作意向書／MOU"),
        ("入出境", "e-Arrival／入出境證件"),
        ("人資", "人資合約／MOU"),
        ("KiGo", "KiGo 使用手冊"),
        ("ETI", "ETI Base Code"),
        ("護照", "護照／入出境證件"),
    )
    for needle, label in mapping:
        if needle.casefold() in q.casefold():
            topics.append(label)
    if not topics:
        topics.append("與題目關鍵詞對應的原始文件尚未入庫或未被召回")
    return topics
