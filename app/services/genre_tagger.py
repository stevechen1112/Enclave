"""ADR-008 / F2 — 文件 genre 標註（catalog 粒度的分類維度）。

初版為規則式（檔名為主、內容片段為輔），設計約束：

- **標註失敗不得擋住入庫**：`tag_document` 永不拋例外，失敗回 "other"。
- 規則必須是通用產品規則（文件類型詞彙），禁止針對評測題幹寫死。
- 枚舉：contract / voucher / manual / travel / policy / form / report / other

日後可換成模型標註（LLM classify），介面不變。
"""
from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

GENRES = ("contract", "voucher", "manual", "travel", "policy", "form", "report", "other")

# 順序即優先序：先命中先贏。規則針對「文件類型」詞彙，不針對特定文件。
_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("voucher", (
        "繳款書", "繳費", "發票", "收據", "切結書", "憑證", "帳單", "繳納",
        "invoice", "receipt", "voucher", "payment",
    )),
    ("travel", (
        "e-arrival", "earrival", "arrival", "入出境", "入境", "出境",
        "簽證", "護照", "機票", "登機", "visa", "passport", "boarding",
    )),
    ("manual", (
        "手冊", "說明書", "操作手冊", "使用指南", "指南", "manual", "guidebook",
        "user guide", "handbook",
    )),
    ("contract", (
        "合約", "契約", "協議", "備忘錄", "意向書", "mou", "agreement",
        "contract", "memo of understanding",
    )),
    ("form", (
        "申請書", "同意書", "申請表", "表單", "切結", "application", "consent",
        "form",
    )),
    ("policy", (
        "工作規則", "辦法", "要點", "公告", "流程", "規章", "職責", "政策",
        "policy", "procedure", "regulation", "sop",
    )),
    ("report", (
        "報告", "分析", "白皮書", "report", "analysis", "whitepaper",
    )),
)


def _normalize(s: str) -> str:
    return (s or "").casefold()


def classify_genre(filename: str, content_sample: Optional[str] = None) -> str:
    """回傳 GENRES 其中之一；永不拋例外。"""
    try:
        name = _normalize(filename)
        for genre, keywords in _RULES:
            if any(k in name for k in keywords):
                return genre
        if content_sample:
            head = _normalize(content_sample[:2000])
            for genre, keywords in _RULES:
                # 內容判定要求詞彙出現多次，降低誤判
                if sum(head.count(k) for k in keywords) >= 3:
                    return genre
        return "other"
    except Exception as exc:  # 標註失敗不得擋住入庫
        logger.warning("genre classify failed for %r: %s", filename, exc)
        return "other"


def tag_document(doc, content_sample: Optional[str] = None) -> str:
    """為 Document ORM 物件標註 genre（就地寫入，呼叫方負責 commit）。"""
    genre = classify_genre(getattr(doc, "filename", "") or "", content_sample)
    try:
        doc.genre = genre
    except Exception as exc:
        logger.warning("genre assign failed: %s", exc)
    return genre


# 查詢側：盤點問句的領域詞 → 可能的 genre 集合（用於 catalog 過濾）。
# 同樣是通用產品規則；查詢不含任何領域詞時回傳空集合（=不過濾）。
QUERY_GENRE_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("財務", "憑證", "發票", "繳款", "帳務", "收據", "報帳"), "voucher"),
    (("合約", "契約", "協議", "備忘錄"), "contract"),
    (("手冊", "說明書", "操作說明"), "manual"),
    (("入出境", "入境", "出境", "出國", "旅行", "簽證", "護照"), "travel"),
    (("人資", "人事", "勞動", "員工", "薪資", "差勤", "工作規則"), "policy"),
    (("表單", "申請書", "同意書"), "form"),
    (("報告", "分析報告"), "report"),
)

_HR_WORDS = ("人資", "人事", "勞動", "員工")


def genres_for_query(query: str) -> set[str]:
    """從查詢抽取 genre 暗示；人資類問題同時涵蓋合約（勞動契約屬合約層）。"""
    q = _normalize(query)
    genres = {
        genre
        for keywords, genre in QUERY_GENRE_HINTS
        if any(kw in q for kw in keywords)
    }
    if "policy" in genres and any(w in q for w in _HR_WORDS):
        genres.add("contract")  # 人資文件常見形態是勞動契約／MOU
    return genres
