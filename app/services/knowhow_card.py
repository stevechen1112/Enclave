"""
P2-1：Know-how Card — 老師傅 know-how 原生知識卡與治理。

稽核文件 §7.4 P0、§11.4 完成定義：
- draft isolation（draft 不可被 RetrievalFacade 命中）
- structured card（適用設備、風險、審核者、版本）
- SOP conflict（SOP 與 know-how 衝突時 SOP 優先並顯示差異）
- reviewer（人工審核）
- effective version（生效版本）
- revocation（撤銷）
- source quote（來源引用）

流程（§7.4）：
  音訊 → STT → knowhow_draft → 結構化知識卡 → SOP 衝突檢查
  → 人工審核 → approved_knowhow → 索引／Wiki

仿照 clause_projection.py 的 DocumentArtifact 承載模式。
"""
from __future__ import annotations

import logging
import uuid as uuid_mod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class KnowhowCardStatus(str, Enum):
    """知識卡狀態機。"""
    DRAFT = "draft"          # 草稿，不可被檢索命中
    PENDING_REVIEW = "pending_review"  # 待審核
    APPROVED = "approved"    # 已核准，可索引
    REJECTED = "rejected"    # 審核拒絕
    SUPERSEDED = "superseded"  # 被新版本取代
    REVOKED = "revoked"      # 撤銷


@dataclass
class KnowhowCard:
    """結構化知識卡。"""
    card_id: str = ""
    title: str = ""
    summary: str = ""
    # 適用設備
    applicable_equipment: List[str] = field(default_factory=list)
    # 風險等級
    risk_level: str = "medium"  # low | medium | high
    # 操作步驟
    steps: List[str] = field(default_factory=list)
    # 注意事項
    cautions: List[str] = field(default_factory=list)
    # 來源引用（source quote）
    source_quotes: List[str] = field(default_factory=list)
    # 審核者
    reviewer: str = ""
    reviewed_at: str = ""
    # 版本
    version: int = 1
    # 狀態
    status: KnowhowCardStatus = KnowhowCardStatus.DRAFT
    # SOP 衝突
    sop_conflicts: List[Dict[str, Any]] = field(default_factory=list)
    # 來源（音訊轉寫、文件等）
    source_type: str = ""  # audio | document | manual
    source_document_id: str = ""
    # 時間戳
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "card_id": self.card_id,
            "title": self.title,
            "summary": self.summary,
            "applicable_equipment": self.applicable_equipment,
            "risk_level": self.risk_level,
            "steps": self.steps,
            "cautions": self.cautions,
            "source_quotes": self.source_quotes,
            "reviewer": self.reviewer,
            "reviewed_at": self.reviewed_at,
            "version": self.version,
            "status": self.status.value,
            "sop_conflicts": self.sop_conflicts,
            "source_type": self.source_type,
            "source_document_id": self.source_document_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @property
    def is_indexable(self) -> bool:
        """是否可被檢索命中（只有 approved 才可）。"""
        return self.status == KnowhowCardStatus.APPROVED


class KnowhowCardManager:
    """知識卡管理器 — draft→approved 生命週期 + SOP 衝突檢查。"""

    def __init__(self):
        self._cards: Dict[str, KnowhowCard] = {}

    def create_draft(
        self,
        title: str,
        summary: str,
        steps: List[str],
        applicable_equipment: Optional[List[str]] = None,
        cautions: Optional[List[str]] = None,
        source_quotes: Optional[List[str]] = None,
        source_type: str = "manual",
        source_document_id: str = "",
        risk_level: str = "medium",
    ) -> KnowhowCard:
        """建立 draft 知識卡。"""
        card = KnowhowCard(
            card_id=str(uuid_mod.uuid4()),
            title=title,
            summary=summary,
            steps=steps,
            applicable_equipment=applicable_equipment or [],
            cautions=cautions or [],
            source_quotes=source_quotes or [],
            source_type=source_type,
            source_document_id=source_document_id,
            risk_level=risk_level,
            status=KnowhowCardStatus.DRAFT,
        )
        self._cards[card.card_id] = card
        logger.info(f"Know-how card draft created: {card.card_id} ({title})")
        return card

    def submit_for_review(
        self,
        card_id: str,
        sop_conflicts: Optional[List[Dict[str, Any]]] = None,
    ) -> KnowhowCard:
        """提交審核。"""
        card = self._get_or_raise(card_id)
        if card.status != KnowhowCardStatus.DRAFT:
            raise ValueError(f"Card {card_id} is not in draft state (current: {card.status.value})")

        card.status = KnowhowCardStatus.PENDING_REVIEW
        card.sop_conflicts = sop_conflicts or []
        card.updated_at = datetime.now(timezone.utc).isoformat()
        logger.info(f"Know-how card submitted for review: {card_id}")
        return card

    def approve(
        self,
        card_id: str,
        reviewer: str,
    ) -> KnowhowCard:
        """核准知識卡（冪等）。"""
        card = self._get_or_raise(card_id)

        # 冪等
        if card.status == KnowhowCardStatus.APPROVED:
            return card

        if card.status not in (KnowhowCardStatus.PENDING_REVIEW, KnowhowCardStatus.REJECTED):
            raise ValueError(f"Cannot approve from state {card.status.value}")

        # 若有未解決的 SOP 衝突，不允許核准
        from app.config import settings
        if settings.KNOWHOW_SOP_CONFLICT_CHECK:
            unresolved = [c for c in card.sop_conflicts if not c.get("resolved")]
            if unresolved:
                raise ValueError(f"Card {card_id} has unresolved SOP conflicts: {len(unresolved)}")

        card.status = KnowhowCardStatus.APPROVED
        card.reviewer = reviewer
        card.reviewed_at = datetime.now(timezone.utc).isoformat()
        card.updated_at = card.reviewed_at
        logger.info(f"Know-how card approved: {card_id} by {reviewer}")
        return card

    def reject(
        self,
        card_id: str,
        reviewer: str,
        reason: str = "",
    ) -> KnowhowCard:
        """拒絕知識卡（冪等）。"""
        card = self._get_or_raise(card_id)

        # 冪等
        if card.status == KnowhowCardStatus.REJECTED:
            return card

        # 只允許從 PENDING_REVIEW 拒絕
        if card.status != KnowhowCardStatus.PENDING_REVIEW:
            raise ValueError(f"Cannot reject from state {card.status.value}")

        card.status = KnowhowCardStatus.REJECTED
        card.reviewer = reviewer
        card.reviewed_at = datetime.now(timezone.utc).isoformat()
        card.updated_at = card.reviewed_at
        logger.info(f"Know-how card rejected: {card_id} by {reviewer}: {reason}")
        return card

    def revoke(self, card_id: str) -> KnowhowCard:
        """撤銷知識卡。"""
        card = self._get_or_raise(card_id)
        card.status = KnowhowCardStatus.REVOKED
        card.updated_at = datetime.now(timezone.utc).isoformat()
        logger.info(f"Know-how card revoked: {card_id}")
        return card

    def supersede(self, card_id: str, new_card_id: str) -> KnowhowCard:
        """用新版本取代舊版本。"""
        card = self._get_or_raise(card_id)
        old_version = card.version
        card.status = KnowhowCardStatus.SUPERSEDED
        card.updated_at = datetime.now(timezone.utc).isoformat()
        # 新卡片版本遞增
        new_card = self._cards.get(new_card_id)
        if new_card:
            new_card.version = old_version + 1
        logger.info(f"Know-how card {card_id} (v{old_version}) superseded by {new_card_id} (v{old_version + 1})")
        return card

    def get_card(self, card_id: str) -> Optional[KnowhowCard]:
        return self._cards.get(card_id)

    def get_indexable_cards(self) -> List[KnowhowCard]:
        """取得可被檢索命中的知識卡（只有 approved）。"""
        return [c for c in self._cards.values() if c.is_indexable]

    def get_pending_review(self) -> List[KnowhowCard]:
        """取得待審核的知識卡。"""
        return [c for c in self._cards.values() if c.status == KnowhowCardStatus.PENDING_REVIEW]

    def _get_or_raise(self, card_id: str) -> KnowhowCard:
        card = self._cards.get(card_id)
        if card is None:
            raise ValueError(f"Know-how card not found: {card_id}")
        return card


# ── 單例 ──

_manager: Optional[KnowhowCardManager] = None


def get_knowhow_manager() -> KnowhowCardManager:
    global _manager
    if _manager is None:
        _manager = KnowhowCardManager()
    return _manager