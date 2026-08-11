"""ADR-008 / F2 — Catalog（文件層）檢索臂。

回答「庫內有哪些檔、什麼類型」這類盤點問題的物理基礎：
直接查 Enclave 主索引的 `documents` 表（ADR-005：不建第四個向量庫），
以 genre（規則標註）＋檔名關鍵字匹配，回傳文件集合而非段落。

契約：
- 只回 `status='completed'` 且未 tombstone 的文件（failed／處理中不得進命中）。
- 每筆命中投影為 RetrievalHit，`granularity='catalog'`、
  `authority_class='primary_document'`、`citation_ok=True`（必有 document_id+filename）。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.services.genre_tagger import genres_for_query

logger = logging.getLogger(__name__)

AUTHORITY_PRIMARY = "primary_document"
AUTHORITY_COMPILED = "compiled_knowledge"
AUTHORITY_EXTERNAL = "external_context"


@dataclass
class RetrievalHit:
    """多粒度統一命中物件（FOUNDATION 計畫 §2.2）。"""
    granularity: str           # catalog | chunk | compiled
    provider: str              # enclave | ragflow | weknora | pipeshub | ...
    authority_class: str       # primary_document | compiled_knowledge | external_context
    document_id: Optional[str]
    filename: Optional[str]
    chunk_index: Optional[int]
    score: float
    content_or_summary: str
    citation_ok: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "granularity": self.granularity,
            "provider": self.provider,
            "authority_class": self.authority_class,
            "document_id": self.document_id,
            "filename": self.filename,
            "chunk_index": self.chunk_index,
            "score": self.score,
            "content": self.content_or_summary,
            "citation_ok": self.citation_ok,
        }


_LATIN_TOKEN = re.compile(r"[a-z0-9][a-z0-9\-_\.]{2,}")
_CJK_TOKEN = re.compile(r"[\u4e00-\u9fff]{2,}")
_QUOTED = re.compile(r"[「『\"']([^」』\"']{1,40})[」』\"']")
_CJK_AFTER_HINT = re.compile(
    r"(?:含有?|出現|包含|關於|關鍵字)\s*[「『\"']?([\u4e00-\u9fffA-Za-z0-9\-_]{2,8})"
)
# 盤點／問句虛詞：不可當檔名過濾條件，否則會誤殺或過寬
_FILENAME_STOP = frozenset({
    "哪些", "列出", "盤點", "清單", "列表", "有什麼", "有哪些", "全部", "文件", "檔案",
    "檔名", "標題", "明顯", "出現", "客戶", "資料", "這批", "裡面", "以及", "或是",
    "請問", "什麼", "含有", "包含", "關於", "相關", "可以", "是否", "如何", "多少",
    "雙方", "標的", "類型", "內容", "主軸", "金額", "報價", "合約", "提案", "方案",
    "總價", "比較", "哪份", "請列", "至少", "三個", "兩個", "一份", "那個",
    "這個", "那些", "目前", "參考", "根據", "說明", "無法", "判讀", "標註",
    "列客戶", "或檔名", "資料裡", "的客戶",
    "談的是", "有無", "或品項", "怎麼寫", "是什麼",
})


def _filename_tokens(query: str) -> list[str]:
    """查詢中可用於檔名比對的 token（拉丁＋中文＋引號片段）。

    盤點題如「檔名含八策」必須能以「八策」過濾 DB 檔名；舊實作只抽拉丁 token，
    會讓中文關鍵字落入「無暗示→全量 top_k」而漏列。
    """
    q = query or ""
    out: list[str] = []
    seen: set[str] = set()

    def _add(tok: str) -> None:
        t = (tok or "").strip().casefold()
        t = re.sub(r"^(含有?|出現|包含)", "", t)
        t = re.sub(r"(的?(?:文件|檔案|客戶)|的)$", "", t)
        t = t.strip()
        if len(t) < 2 or t in _FILENAME_STOP or t in seen:
            return
        if t in {"pdf", "doc", "docx", "xlsx", "the", "and"}:
            return
        # 過長中文片語幾乎不可能是檔名關鍵字
        if len(t) > 12 and not re.search(r"[a-z0-9]", t):
            return
        seen.add(t)
        out.append(t)

    for m in _QUOTED.findall(q):
        _add(m)
    for m in _CJK_AFTER_HINT.findall(q):
        _add(m)
    for t in _LATIN_TOKEN.findall(q.casefold()):
        _add(t)

    # 用虛詞把連續中文打断，再抽短 token（避免整句變成單一 token）
    punched = q
    for sw in sorted(_FILENAME_STOP, key=len, reverse=True):
        punched = punched.replace(sw, " ")
    for t in _CJK_TOKEN.findall(punched):
        _add(t)
    return out


class CatalogRetriever:
    """文件層檢索：genre 過濾 + 檔名 token 匹配，盤點導向（recall 優先）。"""

    def search(
        self,
        *,
        tenant_id: UUID,
        query: str,
        top_k: int = 50,
        genre_filter: Optional[set[str]] = None,
        db=None,
    ) -> List[RetrievalHit]:
        from app.db.session import SessionLocal
        from app.models.document import Document

        own_session = db is None
        session = db or SessionLocal()
        try:
            docs = (
                session.query(Document)
                .filter(
                    Document.tenant_id == tenant_id,
                    Document.status == "completed",
                    Document.tombstoned_at.is_(None),
                )
                .all()
            )
        finally:
            if own_session:
                session.close()

        hinted_genres = set(genre_filter or ()) | genres_for_query(query)
        tokens = _filename_tokens(query)

        hits: List[RetrievalHit] = []
        for d in docs:
            name = (d.filename or "").casefold()
            genre_hit = bool(hinted_genres) and (d.genre in hinted_genres)
            token_hits = [t for t in tokens if t in name]
            if hinted_genres or tokens:
                if not genre_hit and not token_hits:
                    continue
                score = 0.6 * genre_hit + 0.4 * min(len(token_hits), 1) + 0.1 * len(token_hits)
            else:
                # 無任何領域暗示的純盤點（「有哪些文件」）→ 全量列出
                score = 0.5
            hits.append(RetrievalHit(
                granularity="catalog",
                provider="enclave",
                authority_class=AUTHORITY_PRIMARY,
                document_id=str(d.id),
                filename=d.filename,
                chunk_index=None,
                score=round(float(score), 4),
                content_or_summary=(
                    f"文件：{d.filename}（類型：{d.genre or 'other'}，"
                    "狀態：已完成入庫）"
                ),
                citation_ok=True,
            ))

        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:top_k]

    def filename_token_hit(
        self,
        *,
        tenant_id: UUID,
        tokens: List[str],
        db=None,
    ) -> bool:
        """任一 token 命中租戶已完成文件的檔名即回 True。

        供 catalog 臂的前置判斷：只在檔名索引實際命中時才掛臂，
        避免一般問答（如「加班費怎麼算」）誤觸發盤點查詢。
        """
        from sqlalchemy import or_

        from app.db.session import SessionLocal
        from app.models.document import Document

        clauses = []
        for t in tokens:
            clean = str(t or "").replace("%", "").replace("_", "").strip()
            if clean:
                clauses.append(Document.filename.ilike(f"%{clean}%"))
        if not clauses:
            return False

        own_session = db is None
        session = db or SessionLocal()
        try:
            return (
                session.query(Document.id)
                .filter(
                    Document.tenant_id == tenant_id,
                    Document.status == "completed",
                    Document.tombstoned_at.is_(None),
                    or_(*clauses),
                )
                .limit(1)
                .first()
                is not None
            )
        finally:
            if own_session:
                session.close()


_retriever: Optional[CatalogRetriever] = None


def get_catalog_retriever() -> CatalogRetriever:
    global _retriever
    if _retriever is None:
        _retriever = CatalogRetriever()
    return _retriever
