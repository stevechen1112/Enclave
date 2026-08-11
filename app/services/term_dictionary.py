"""
MKA Tenant Term Dictionary — 公司專有詞字典服務。

對照 ENGINEERING_PLAN.md §4.5：
- 公司專有名詞、料號、客戶名、設備代碼
- 中英混用、常見誤聽
- 用於 STT 後處理（修正誤聽）和檢索增強
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class TermDictionaryService:
    """公司專有詞字典服務。"""

    def __init__(self, db: Session):
        self.db = db

    def add_term(
        self,
        tenant_id: UUID,
        term: str,
        aliases: Optional[List[str]] = None,
        phonetic_hints: Optional[List[str]] = None,
        category: str = "general",
        scope: str = "global",
        source: str = "manual",
    ) -> Dict[str, Any]:
        """新增專有詞。"""
        from app.models.mka import TenantTermDictionary

        existing = (
            self.db.query(TenantTermDictionary)
            .filter(
                TenantTermDictionary.tenant_id == tenant_id,
                TenantTermDictionary.term == term,
            )
            .first()
        )
        if existing:
            # 更新
            if aliases is not None:
                existing.aliases = aliases
            if phonetic_hints is not None:
                existing.phonetic_hints = phonetic_hints
            existing.category = category
            existing.scope = scope
            existing.source = source
            self.db.commit()
            return self._to_dict(existing)

        entry = TenantTermDictionary(
            tenant_id=tenant_id,
            term=term,
            aliases=aliases or [],
            phonetic_hints=phonetic_hints or [],
            category=category,
            scope=scope,
            source=source,
            active=True,
        )
        self.db.add(entry)
        self.db.commit()
        logger.info(f"Term added: {term} ({category}) for tenant {tenant_id}")
        return self._to_dict(entry)

    def list_terms(
        self,
        tenant_id: UUID,
        category: Optional[str] = None,
        active_only: bool = True,
    ) -> List[Dict[str, Any]]:
        """列出專有詞。"""
        from app.models.mka import TenantTermDictionary

        query = self.db.query(TenantTermDictionary).filter(
            TenantTermDictionary.tenant_id == tenant_id
        )
        if active_only:
            query = query.filter(TenantTermDictionary.active.is_(True))
        if category:
            query = query.filter(TenantTermDictionary.category == category)

        return [self._to_dict(t) for t in query.all()]

    def search_terms(
        self,
        tenant_id: UUID,
        query: str,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """搜尋專有詞（用於 STT 後處理）。"""
        from app.models.mka import TenantTermDictionary

        terms = (
            self.db.query(TenantTermDictionary)
            .filter(
                TenantTermDictionary.tenant_id == tenant_id,
                TenantTermDictionary.active.is_(True),
            )
            .all()
        )

        # 簡易搜尋：term 或 aliases 包含 query
        results = []
        query_lower = query.lower()
        for t in terms:
            if query_lower in t.term.lower():
                results.append(self._to_dict(t))
            elif t.aliases and any(query_lower in a.lower() for a in t.aliases):
                results.append(self._to_dict(t))
            if len(results) >= limit:
                break

        return results

    def correct_transcript(
        self,
        tenant_id: UUID,
        transcript: str,
    ) -> str:
        """用專有詞字典修正 STT 轉寫結果。

        策略：
        1. 載入所有 active terms + aliases
        2. 對 transcript 做逐詞比對
        3. 若發現誤聽詞（phonetic_hints 匹配），替換為正確 term
        """
        from app.models.mka import TenantTermDictionary

        terms = (
            self.db.query(TenantTermDictionary)
            .filter(
                TenantTermDictionary.tenant_id == tenant_id,
                TenantTermDictionary.active.is_(True),
            )
            .all()
        )

        corrected = transcript
        for term in terms:
            # 檢查 phonetic_hints（常見誤聽）
            for hint in term.phonetic_hints or []:
                if hint and hint in corrected:
                    corrected = corrected.replace(hint, term.term)
                    logger.info(f"STT correction: '{hint}' → '{term.term}'")

            # 檢查 aliases
            for alias in term.aliases or []:
                if alias and alias in corrected and alias != term.term:
                    corrected = corrected.replace(alias, term.term)

        return corrected

    def deactivate_term(self, tenant_id: UUID, term: str) -> bool:
        """停用專有詞。"""
        from app.models.mka import TenantTermDictionary

        entry = (
            self.db.query(TenantTermDictionary)
            .filter(
                TenantTermDictionary.tenant_id == tenant_id,
                TenantTermDictionary.term == term,
            )
            .first()
        )
        if entry:
            entry.active = False
            self.db.commit()
            return True
        return False

    def _to_dict(self, entry: Any) -> Dict[str, Any]:
        return {
            "id": str(entry.id),
            "tenant_id": str(entry.tenant_id),
            "term": entry.term,
            "aliases": entry.aliases or [],
            "phonetic_hints": entry.phonetic_hints or [],
            "category": entry.category,
            "scope": entry.scope,
            "active": entry.active,
            "source": entry.source,
            "last_verified_at": entry.last_verified_at.isoformat() if entry.last_verified_at else None,
        }


def get_term_dictionary_service(db: Session) -> TermDictionaryService:
    return TermDictionaryService(db)