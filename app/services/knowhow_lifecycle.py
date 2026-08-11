"""
MKA-P5：Know-how 生命週期管理 — DB-backed lineage / review reminder / purge。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

logger = logging.getLogger(__name__)


@dataclass
class AudioLineage:
    audio_uri: str = ""
    transcript_id: str = ""
    recorded_at: str = ""
    recorded_by: str = ""
    duration_seconds: float = 0.0
    retention_policy: str = "transcript_only"
    expires_at: str = ""
    consent_obtained: bool = False
    consent_at: str = ""
    consent_by: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "audio_uri": self.audio_uri,
            "transcript_id": self.transcript_id,
            "recorded_at": self.recorded_at,
            "recorded_by": self.recorded_by,
            "duration_seconds": self.duration_seconds,
            "retention_policy": self.retention_policy,
            "expires_at": self.expires_at,
            "consent_obtained": self.consent_obtained,
            "consent_at": self.consent_at,
            "consent_by": self.consent_by,
        }


@dataclass
class ReviewReminder:
    card_id: str = ""
    card_title: str = ""
    reviewer: str = ""
    due_at: str = ""
    reminder_type: str = "expiry"
    message: str = ""
    sent: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "card_id": self.card_id,
            "card_title": self.card_title,
            "reviewer": self.reviewer,
            "due_at": self.due_at,
            "reminder_type": self.reminder_type,
            "message": self.message,
            "sent": self.sent,
        }


class KnowhowLifecycleManager:
    def __init__(self, db: Any = None, tenant_id: Optional[UUID] = None):
        self.db = db
        self.tenant_id = tenant_id
        self._lineages: Dict[str, AudioLineage] = {}
        self._reminders: List[ReviewReminder] = []

    def record_lineage(
        self,
        card_id: Any,
        audio_uri: str = "",
        transcript_id: str = "",
        recorded_by: Any = "",
        duration_seconds: float = 0.0,
        retention_policy: str = "transcript_only",
        consent_obtained: bool = False,
        consent_by: Any = "",
    ) -> AudioLineage:
        now = datetime.now(timezone.utc)
        if retention_policy == "audio_and_transcript":
            expires = now + timedelta(days=90)
        elif retention_policy == "transcript_only":
            expires = now + timedelta(days=365)
        else:
            expires = now

        lineage = AudioLineage(
            audio_uri=audio_uri or "",
            transcript_id=str(transcript_id or ""),
            recorded_at=now.isoformat(),
            recorded_by=str(recorded_by or ""),
            duration_seconds=duration_seconds,
            retention_policy=retention_policy,
            expires_at=expires.isoformat(),
            consent_obtained=consent_obtained,
            consent_at=now.isoformat() if consent_obtained else "",
            consent_by=str(consent_by or ""),
        )
        key = str(card_id)
        self._lineages[key] = lineage

        if self.db is not None and self.tenant_id is not None:
            from app.models.mka import KnowhowLineage

            cid = card_id if isinstance(card_id, UUID) else UUID(str(card_id))
            row = KnowhowLineage(
                tenant_id=self.tenant_id,
                card_id=cid,
                audio_uri=lineage.audio_uri or None,
                transcript_id=lineage.transcript_id or None,
                recorded_at=now,
                recorded_by=UUID(str(recorded_by)) if recorded_by else None,
                duration_seconds=duration_seconds,
                retention_policy=retention_policy,
                expires_at=expires,
                consent_obtained=consent_obtained,
                consent_at=now if consent_obtained else None,
                consent_by=UUID(str(consent_by)) if consent_by else None,
            )
            self.db.add(row)
            try:
                self.db.flush()
            except Exception as exc:
                logger.warning("lineage persist failed: %s", exc)
        return lineage

    def get_lineage(self, card_id: str) -> Optional[AudioLineage]:
        key = str(card_id)
        if key in self._lineages:
            return self._lineages[key]
        if self.db is None or self.tenant_id is None:
            return None
        from app.models.mka import KnowhowLineage
        try:
            cid = UUID(str(card_id))
        except Exception:
            return None
        row = (
            self.db.query(KnowhowLineage)
            .filter(
                KnowhowLineage.tenant_id == self.tenant_id,
                KnowhowLineage.card_id == cid,
            )
            .order_by(KnowhowLineage.created_at.desc())
            .first()
        )
        if row is None:
            return None
        return AudioLineage(
            audio_uri=row.audio_uri or "",
            transcript_id=row.transcript_id or "",
            recorded_at=row.recorded_at.isoformat() if row.recorded_at else "",
            recorded_by=str(row.recorded_by or ""),
            duration_seconds=row.duration_seconds or 0.0,
            retention_policy=row.retention_policy or "transcript_only",
            expires_at=row.expires_at.isoformat() if row.expires_at else "",
            consent_obtained=bool(row.consent_obtained),
            consent_at=row.consent_at.isoformat() if row.consent_at else "",
            consent_by=str(row.consent_by or ""),
        )

    def check_expiry(self, card_id: str, expires_at: str) -> bool:
        if not expires_at:
            return False
        try:
            expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            return datetime.now(timezone.utc) > expiry
        except (ValueError, AttributeError):
            return False

    def create_review_reminder(
        self,
        card_id: str,
        card_title: str,
        reviewer: str,
        due_at: str,
        reminder_type: str = "expiry",
        message: str = "",
    ) -> ReviewReminder:
        reminder = ReviewReminder(
            card_id=str(card_id),
            card_title=card_title,
            reviewer=reviewer,
            due_at=due_at,
            reminder_type=reminder_type,
            message=message or f"知識卡「{card_title}」需要複核",
        )
        self._reminders.append(reminder)
        if self.db is not None and self.tenant_id is not None:
            from app.models.mka import MKAReviewReminder
            try:
                due = datetime.fromisoformat(due_at.replace("Z", "+00:00"))
            except Exception:
                due = datetime.now(timezone.utc) + timedelta(days=30)
            try:
                cid = UUID(str(card_id))
            except Exception:
                return reminder
            reviewer_id = None
            try:
                reviewer_id = UUID(str(reviewer)) if reviewer else None
            except Exception:
                reviewer_id = None
            self.db.add(
                MKAReviewReminder(
                    tenant_id=self.tenant_id,
                    card_id=cid,
                    card_title=card_title,
                    reviewer_id=reviewer_id,
                    due_at=due,
                    reminder_type=reminder_type,
                    message=reminder.message,
                    sent=False,
                )
            )
            try:
                self.db.flush()
            except Exception as exc:
                logger.warning("reminder persist failed: %s", exc)
        return reminder

    def get_pending_reminders(self) -> List[ReviewReminder]:
        if self.db is not None and self.tenant_id is not None:
            from app.models.mka import MKAReviewReminder
            rows = (
                self.db.query(MKAReviewReminder)
                .filter(
                    MKAReviewReminder.tenant_id == self.tenant_id,
                    MKAReviewReminder.sent.is_(False),
                )
                .limit(200)
                .all()
            )
            return [
                ReviewReminder(
                    card_id=str(r.card_id),
                    card_title=r.card_title or "",
                    reviewer=str(r.reviewer_id or ""),
                    due_at=r.due_at.isoformat() if r.due_at else "",
                    reminder_type=r.reminder_type or "expiry",
                    message=r.message or "",
                    sent=False,
                )
                for r in rows
            ]
        return [r for r in self._reminders if not r.sent]

    def mark_reminder_sent(self, card_id: str) -> None:
        for r in self._reminders:
            if r.card_id == str(card_id):
                r.sent = True
        if self.db is not None and self.tenant_id is not None:
            from app.models.mka import MKAReviewReminder
            try:
                cid = UUID(str(card_id))
            except Exception:
                return
            rows = (
                self.db.query(MKAReviewReminder)
                .filter(
                    MKAReviewReminder.tenant_id == self.tenant_id,
                    MKAReviewReminder.card_id == cid,
                    MKAReviewReminder.sent.is_(False),
                )
                .all()
            )
            now = datetime.now(timezone.utc)
            for row in rows:
                row.sent = True
                row.sent_at = now
            try:
                self.db.flush()
            except Exception:
                pass

    def check_consent_required(self, card_id: str) -> bool:
        lineage = self.get_lineage(card_id)
        if lineage and lineage.audio_uri:
            return not lineage.consent_obtained
        return False

    def purge_expired_audio(self, card_id: str) -> bool:
        lineage = self.get_lineage(card_id)
        if not lineage:
            return False
        if self.check_expiry(card_id, lineage.expires_at):
            lineage.audio_uri = ""
            lineage.retention_policy = "transcript_only"
            if self.db is not None and self.tenant_id is not None:
                from app.models.mka import KnowhowLineage
                try:
                    cid = UUID(str(card_id))
                except Exception:
                    return True
                rows = (
                    self.db.query(KnowhowLineage)
                    .filter(
                        KnowhowLineage.tenant_id == self.tenant_id,
                        KnowhowLineage.card_id == cid,
                    )
                    .all()
                )
                for row in rows:
                    row.audio_uri = None
                    row.retention_policy = "transcript_only"
                try:
                    self.db.flush()
                except Exception:
                    pass
            logger.info("Audio purged for card %s (expired)", card_id)
            return True
        return False


_lifecycle_manager: Optional[KnowhowLifecycleManager] = None


def get_knowhow_lifecycle_manager(db: Any = None, tenant_id: Optional[UUID] = None) -> KnowhowLifecycleManager:
    if db is not None:
        return KnowhowLifecycleManager(db=db, tenant_id=tenant_id)
    global _lifecycle_manager
    if _lifecycle_manager is None:
        _lifecycle_manager = KnowhowLifecycleManager()
    return _lifecycle_manager
