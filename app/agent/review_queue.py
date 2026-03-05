"""
Phase 10 — 人工審核佇列 (Review Queue)

管理 AI 分類提案的生命週期：
  pending   → 等待人工審核
  approved  → 人工確認，排入向量化佇列
  modified  → 人工修改後確認
  rejected  → 拒絕入庫（保留記錄）
  processing → 向量化進行中
  indexed   → 已入知識庫
"""

import logging
from datetime import datetime, UTC
from enum import Enum
from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.review_item import ReviewItem

logger = logging.getLogger(__name__)


class ReviewStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    MODIFIED = "modified"
    REJECTED = "rejected"
    PROCESSING = "processing"
    INDEXED = "indexed"
    FAILED = "failed"


class ReviewQueueManager:
    """審核佇列業務邏輯層（同步 SQLAlchemy Session）。"""

    def __init__(self, db: Session):
        self.db = db

    # ── 寫入 ────────────────────────────────────────────────────────────────────

    def enqueue(self, proposal, tenant_id) -> str:
        """將 ClassificationProposal 加入審核佇列，回傳 review_item_id。
        
        P10-6: 在入佇列時自動偵測跨文件關聯（相同當事人 / 相同分類），
        並將關聯文件清單寫入 suggested_tags["_related_ids"]。
        """
        # Cross-document association detection (P10-6)
        related = self._find_related(proposal, tenant_id)
        tags = dict(proposal.suggested_tags) if proposal.suggested_tags else {}
        if related:
            tags["_related_ids"] = related

        item = ReviewItem(
            tenant_id=tenant_id,
            file_path=proposal.file_path,
            file_name=proposal.file_name,
            file_size=proposal.file_size,
            file_ext=proposal.file_ext,
            suggested_category=proposal.suggested_category,
            suggested_subcategory=proposal.suggested_subcategory,
            suggested_tags=tags,
            confidence_score=proposal.confidence_score,
            reasoning=proposal.reasoning,
            status=ReviewStatus.PENDING,
        )
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        logger.info("Enqueued review item %s for %s", item.id, proposal.file_name)
        return str(item.id)

    def _find_related(self, proposal, tenant_id) -> list:
        """P10-6: 搜尋相同組織中與本提案相關的既有文件。

        關聯判斷條件（OR 邏輯）：
          1. suggested_tags["person"] 相同（同名當事人）
          2. suggested_category 相同 且 檔名日期相同（同案件日期批次）

        回傳最多 10 筆 [{id, file_name, match_reason}]。
        """
        tags = proposal.suggested_tags or {}
        person = tags.get("person")
        date = tags.get("date")
        category = proposal.suggested_category

        results: list = []
        seen_ids: set = set()

        # Match by person name
        if person:
            try:
                rows = (
                    self.db.query(ReviewItem.id, ReviewItem.file_name)
                    .filter(
                        ReviewItem.tenant_id == tenant_id,
                        ReviewItem.suggested_tags["person"].astext == person,
                        ReviewItem.status.notin_(["rejected"]),
                    )
                    .limit(10)
                    .all()
                )
                for r in rows:
                    sid = str(r.id)
                    if sid not in seen_ids:
                        seen_ids.add(sid)
                        results.append({"id": sid, "file_name": r.file_name, "match": "person"})
            except Exception:
                pass  # JSONB path query may not be supported in some pg versions

        # Match by category + date
        if category and date and len(results) < 10:
            try:
                rows = (
                    self.db.query(ReviewItem.id, ReviewItem.file_name)
                    .filter(
                        ReviewItem.tenant_id == tenant_id,
                        ReviewItem.suggested_category == category,
                        ReviewItem.suggested_tags["date"].astext == date,
                        ReviewItem.status.notin_(["rejected"]),
                    )
                    .limit(10 - len(results))
                    .all()
                )
                for r in rows:
                    sid = str(r.id)
                    if sid not in seen_ids:
                        seen_ids.add(sid)
                        results.append({"id": sid, "file_name": r.file_name, "match": "date+category"})
            except Exception:
                pass

        return results[:10]

    def approve(self, item_id: UUID, approved_by: UUID) -> bool:
        """核准單一項目，觸發向量化任務。"""
        item = self.db.query(ReviewItem).filter(ReviewItem.id == item_id).first()
        if not item or item.status not in (ReviewStatus.PENDING, ReviewStatus.MODIFIED):
            return False

        item.status = ReviewStatus.APPROVED
        item.reviewer_id = approved_by
        item.reviewed_at = datetime.now(UTC)
        self.db.commit()

        self._trigger_indexing(item)
        return True

    def batch_approve(self, item_ids: List[UUID], approved_by: UUID) -> int:
        """批量核准，回傳成功數量。"""
        count = 0
        for item_id in item_ids:
            if self.approve(item_id, approved_by):
                count += 1
        return count

    def reject(self, item_id: UUID, reason: str, rejected_by: UUID) -> bool:
        """拒絕入庫，保留記錄。"""
        item = self.db.query(ReviewItem).filter(ReviewItem.id == item_id).first()
        if not item:
            return False
        item.status = ReviewStatus.REJECTED
        item.reviewer_id = rejected_by
        item.review_note = reason
        item.reviewed_at = datetime.now(UTC)
        self.db.commit()
        return True

    def modify_and_approve(
        self, item_id: UUID, corrections: dict, approved_by: UUID
    ) -> bool:
        """人工修改分類後確認，記錄修改內容。"""
        item = self.db.query(ReviewItem).filter(ReviewItem.id == item_id).first()
        if not item:
            return False

        item.approved_category = corrections.get("category", item.suggested_category)
        item.approved_tags = corrections.get("tags", item.suggested_tags)
        item.review_note = corrections.get("note", "")
        item.status = ReviewStatus.MODIFIED
        item.reviewer_id = approved_by
        item.reviewed_at = datetime.now(UTC)
        self.db.commit()

        self._trigger_indexing(item)
        return True

    # ── 查詢 ────────────────────────────────────────────────────────────────────

    def get_pending_items(
        self,
        tenant_id=None,
        min_confidence: Optional[float] = None,
        max_confidence: Optional[float] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple:
        """取得待審核清單，回傳 (items, total)。"""
        q = self.db.query(ReviewItem)

        if tenant_id:
            q = q.filter(ReviewItem.tenant_id == tenant_id)
        if status:
            q = q.filter(ReviewItem.status == status)
        else:
            q = q.filter(ReviewItem.status == ReviewStatus.PENDING)
        if min_confidence is not None:
            q = q.filter(ReviewItem.confidence_score >= min_confidence)
        if max_confidence is not None:
            q = q.filter(ReviewItem.confidence_score <= max_confidence)

        total = q.count()
        items = q.order_by(ReviewItem.created_at.desc()).offset(offset).limit(limit).all()
        return items, total

    def get_item(self, item_id: UUID) -> Optional[ReviewItem]:
        return self.db.query(ReviewItem).filter(ReviewItem.id == item_id).first()

    def get_counts_by_status(self, tenant_id=None) -> dict:
        """各狀態的數量統計。"""
        from sqlalchemy import func
        q = self.db.query(ReviewItem.status, func.count(ReviewItem.id).label("cnt"))
        if tenant_id:
            q = q.filter(ReviewItem.tenant_id == tenant_id)
        rows = q.group_by(ReviewItem.status).all()
        return {r.status: r.cnt for r in rows}

    # ── 私有 ────────────────────────────────────────────────────────────────────

    def _trigger_indexing(self, item: ReviewItem) -> None:
        """核准後送入 Celery 向量化任務。"""
        try:
            from app.tasks.document_tasks import watcher_ingest_file_task
            watcher_ingest_file_task.delay(
                file_path=item.file_path,
                tenant_id=str(item.tenant_id),
                user_id=str(item.reviewer_id) if item.reviewer_id else None,
                skip_if_current=False,
            )
            item.status = ReviewStatus.PROCESSING
            self.db.commit()
        except Exception as exc:
            logger.error("_trigger_indexing failed for item %s: %s", item.id, exc)

