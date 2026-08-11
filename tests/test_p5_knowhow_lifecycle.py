"""
MKA P5 — Know-how 生命週期測試。
"""
import pytest
from datetime import datetime, timedelta, timezone

from app.services.knowhow_lifecycle import (
    AudioLineage, ReviewReminder, KnowhowLifecycleManager,
    get_knowhow_lifecycle_manager,
)


class TestAudioLineage:
    def test_record_lineage(self):
        mgr = KnowhowLifecycleManager()
        lineage = mgr.record_lineage(
            card_id="card-001",
            audio_uri="s3://bucket/audio/001.wav",
            transcript_id="trans-001",
            recorded_by="user-001",
            duration_seconds=120.0,
            retention_policy="transcript_only",
            consent_obtained=True,
            consent_by="interviewee-001",
        )
        assert lineage.audio_uri == "s3://bucket/audio/001.wav"
        assert lineage.consent_obtained is True
        assert lineage.expires_at != ""

    def test_get_lineage(self):
        mgr = KnowhowLifecycleManager()
        mgr.record_lineage(card_id="card-002", audio_uri="uri")
        lineage = mgr.get_lineage("card-002")
        assert lineage is not None
        assert lineage.audio_uri == "uri"

    def test_get_lineage_not_found(self):
        mgr = KnowhowLifecycleManager()
        assert mgr.get_lineage("nonexistent") is None


class TestExpiryCheck:
    def test_not_expired(self):
        mgr = KnowhowLifecycleManager()
        future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        assert mgr.check_expiry("card", future) is False

    def test_expired(self):
        mgr = KnowhowLifecycleManager()
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        assert mgr.check_expiry("card", past) is True

    def test_no_expiry(self):
        mgr = KnowhowLifecycleManager()
        assert mgr.check_expiry("card", "") is False


class TestReviewReminder:
    def test_create_reminder(self):
        mgr = KnowhowLifecycleManager()
        reminder = mgr.create_review_reminder(
            card_id="card-001",
            card_title="CNC 操作要領",
            reviewer="admin",
            due_at="2026-12-31",
            reminder_type="expiry",
        )
        assert reminder.card_id == "card-001"
        assert reminder.sent is False
        assert "CNC 操作要領" in reminder.message

    def test_get_pending_reminders(self):
        mgr = KnowhowLifecycleManager()
        mgr.create_review_reminder("c1", "t1", "r1", "2026-12-31")
        mgr.create_review_reminder("c2", "t2", "r2", "2026-12-31")
        pending = mgr.get_pending_reminders()
        assert len(pending) >= 2

    def test_mark_reminder_sent(self):
        mgr = KnowhowLifecycleManager()
        mgr.create_review_reminder("c3", "t3", "r3", "2026-12-31")
        mgr.mark_reminder_sent("c3")
        pending = mgr.get_pending_reminders()
        assert all(r.card_id != "c3" for r in pending)


class TestConsentCheck:
    def test_consent_required_no_consent(self):
        mgr = KnowhowLifecycleManager()
        mgr.record_lineage(
            card_id="card-003",
            audio_uri="uri",
            consent_obtained=False,
        )
        assert mgr.check_consent_required("card-003") is True

    def test_consent_not_required_with_consent(self):
        mgr = KnowhowLifecycleManager()
        mgr.record_lineage(
            card_id="card-004",
            audio_uri="uri",
            consent_obtained=True,
            consent_by="interviewee",
        )
        assert mgr.check_consent_required("card-004") is False

    def test_consent_not_required_no_audio(self):
        mgr = KnowhowLifecycleManager()
        mgr.record_lineage(card_id="card-005", audio_uri="")
        assert mgr.check_consent_required("card-005") is False


class TestPurgeExpiredAudio:
    def test_purge_expired(self):
        mgr = KnowhowLifecycleManager()
        # 設定已過期的 lineage
        lineage = mgr.record_lineage(
            card_id="card-006",
            audio_uri="s3://bucket/old.wav",
            retention_policy="none",  # 立即過期
        )
        purged = mgr.purge_expired_audio("card-006")
        assert purged is True
        assert lineage.audio_uri == ""
        assert lineage.retention_policy == "transcript_only"

    def test_purge_not_expired(self):
        mgr = KnowhowLifecycleManager()
        mgr.record_lineage(
            card_id="card-007",
            audio_uri="s3://bucket/active.wav",
            retention_policy="transcript_only",  # 365 天後過期
        )
        purged = mgr.purge_expired_audio("card-007")
        assert purged is False

    def test_purge_not_found(self):
        mgr = KnowhowLifecycleManager()
        assert mgr.purge_expired_audio("nonexistent") is False