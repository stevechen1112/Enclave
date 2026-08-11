"""
MKA 音訊 retention 與成本記錄。

對照 ENGINEERING_PLAN.md §12.1、§13.4：
- tenant policy 決定是否保存音訊
- 預設保存 transcript，不一定保存 audio
- 支援 retention 與硬刪
- 每個完成任務記錄 COGS（STT/LLM/embedding/rerank/OCR/storage）

本模組提供兩層：
1. 記憶體 AudioRetentionManager — 純政策計算與預設值（單元測試／無 DB 情境）
2. DB-backed `*_db` 函式 — 正式路徑；政策與成本記錄持久化於
   ``mka_audio_policies``／``mka_task_costs``，purge 由 Celery beat 每日執行
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.mka import InteractionSession, MKAAudioPolicy, MKATaskCost

logger = logging.getLogger(__name__)


@dataclass
class AudioRetentionPolicy:
    """音訊保留政策。"""
    tenant_id: str = ""
    save_audio: bool = False  # 預設不保存音訊
    save_transcript: bool = True  # 預設保存轉寫
    audio_retention_days: int = 90  # 音訊保留天數
    transcript_retention_days: int = 365  # 轉寫保留天數
    encrypt_at_rest: bool = True
    audit_downloads: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "save_audio": self.save_audio,
            "save_transcript": self.save_transcript,
            "audio_retention_days": self.audio_retention_days,
            "transcript_retention_days": self.transcript_retention_days,
            "encrypt_at_rest": self.encrypt_at_rest,
            "audit_downloads": self.audit_downloads,
        }


@dataclass
class TaskCostRecord:
    """任務成本記錄（§13.4 COGS）。"""
    task_id: str = ""
    tenant_id: str = ""
    correlation_id: str = ""
    # 成本細項
    stt_cost: float = 0.0
    llm_cost: float = 0.0
    embedding_cost: float = 0.0
    rerank_cost: float = 0.0
    ocr_cost: float = 0.0
    source_verify_cost: float = 0.0
    storage_cost: float = 0.0
    # 統計
    total_cost: float = 0.0
    # 時間
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self):
        self.total_cost = (
            self.stt_cost + self.llm_cost + self.embedding_cost +
            self.rerank_cost + self.ocr_cost + self.source_verify_cost +
            self.storage_cost
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "tenant_id": self.tenant_id,
            "correlation_id": self.correlation_id,
            "stt_cost": self.stt_cost,
            "llm_cost": self.llm_cost,
            "embedding_cost": self.embedding_cost,
            "rerank_cost": self.rerank_cost,
            "ocr_cost": self.ocr_cost,
            "source_verify_cost": self.source_verify_cost,
            "storage_cost": self.storage_cost,
            "total_cost": self.total_cost,
            "created_at": self.created_at,
        }


class AudioRetentionManager:
    """音訊保留管理器。"""

    def __init__(self):
        self._policies: Dict[str, AudioRetentionPolicy] = {}
        self._cost_records: List[TaskCostRecord] = []

    def set_policy(self, policy: AudioRetentionPolicy) -> None:
        """設定租戶音訊保留政策。"""
        self._policies[policy.tenant_id] = policy
        logger.info(f"Audio retention policy set for tenant {policy.tenant_id}: save_audio={policy.save_audio}")

    def get_policy(self, tenant_id: str) -> AudioRetentionPolicy:
        """取得租戶音訊保留政策（無設定時回傳預設）。"""
        return self._policies.get(tenant_id, AudioRetentionPolicy(tenant_id=tenant_id))

    def should_save_audio(self, tenant_id: str) -> bool:
        """是否應保存音訊。"""
        return self.get_policy(tenant_id).save_audio

    def should_save_transcript(self, tenant_id: str) -> bool:
        """是否應保存轉寫。"""
        return self.get_policy(tenant_id).save_transcript

    def get_audio_expiry(self, tenant_id: str, recorded_at: datetime) -> datetime:
        """取得音訊過期時間。"""
        policy = self.get_policy(tenant_id)
        return recorded_at + timedelta(days=policy.audio_retention_days)

    def get_transcript_expiry(self, tenant_id: str, recorded_at: datetime) -> datetime:
        """取得轉寫過期時間。"""
        policy = self.get_policy(tenant_id)
        return recorded_at + timedelta(days=policy.transcript_retention_days)

    def record_cost(self, record: TaskCostRecord) -> None:
        """記錄任務成本。"""
        self._cost_records.append(record)
        logger.info(
            f"Cost recorded: task={record.task_id}, total={record.total_cost:.4f}"
        )

    def get_cost_summary(
        self,
        tenant_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """取得成本摘要。"""
        records = [r for r in self._cost_records if r.tenant_id == tenant_id]

        if start_date:
            records = [r for r in records if r.created_at >= start_date]
        if end_date:
            records = [r for r in records if r.created_at <= end_date]

        if not records:
            return {"tenant_id": tenant_id, "total_tasks": 0, "total_cost": 0.0}

        return {
            "tenant_id": tenant_id,
            "total_tasks": len(records),
            "total_cost": sum(r.total_cost for r in records),
            "avg_cost_per_task": sum(r.total_cost for r in records) / len(records),
            "cost_breakdown": {
                "stt": sum(r.stt_cost for r in records),
                "llm": sum(r.llm_cost for r in records),
                "embedding": sum(r.embedding_cost for r in records),
                "rerank": sum(r.rerank_cost for r in records),
                "ocr": sum(r.ocr_cost for r in records),
                "source_verify": sum(r.source_verify_cost for r in records),
                "storage": sum(r.storage_cost for r in records),
            },
        }


# ── 單例 ──

_retention_manager: Optional[AudioRetentionManager] = None


def get_audio_retention_manager() -> AudioRetentionManager:
    global _retention_manager
    if _retention_manager is None:
        _retention_manager = AudioRetentionManager()
    return _retention_manager


# ═══════════════════════════════════════════════════════════════════════════════
#  DB-backed 正式路徑（request session 注入；禁止 process-wide session）
# ═══════════════════════════════════════════════════════════════════════════════

_COST_FIELDS = (
    "stt_cost", "llm_cost", "embedding_cost", "rerank_cost",
    "ocr_cost", "source_verify_cost", "storage_cost",
)


def _policy_from_row(row: MKAAudioPolicy) -> AudioRetentionPolicy:
    return AudioRetentionPolicy(
        tenant_id=str(row.tenant_id),
        save_audio=bool(row.save_audio),
        save_transcript=bool(row.save_transcript),
        audio_retention_days=int(row.audio_retention_days or 90),
        transcript_retention_days=int(row.transcript_retention_days or 365),
        encrypt_at_rest=bool(row.encrypt_at_rest),
        audit_downloads=bool(row.audit_downloads),
    )


def get_policy_db(db: Session, tenant_id: UUID) -> AudioRetentionPolicy:
    """取得租戶政策；無記錄時回傳預設（不寫入）。"""
    row = (
        db.query(MKAAudioPolicy)
        .filter(MKAAudioPolicy.tenant_id == tenant_id)
        .first()
    )
    if row is None:
        return AudioRetentionPolicy(tenant_id=str(tenant_id))
    return _policy_from_row(row)


def set_policy_db(db: Session, tenant_id: UUID, **fields: Any) -> AudioRetentionPolicy:
    """Upsert 租戶政策。"""
    allowed = {
        "save_audio", "save_transcript", "audio_retention_days",
        "transcript_retention_days", "encrypt_at_rest", "audit_downloads",
    }
    row = (
        db.query(MKAAudioPolicy)
        .filter(MKAAudioPolicy.tenant_id == tenant_id)
        .first()
    )
    if row is None:
        row = MKAAudioPolicy(tenant_id=tenant_id)
        db.add(row)
    for key, value in fields.items():
        if key in allowed:
            setattr(row, key, value)
    db.flush()
    return _policy_from_row(row)


def record_cost_db(
    db: Session,
    *,
    tenant_id: UUID,
    task_type: str,
    task_id: str = "",
    correlation_id: str = "",
    details: Optional[Dict[str, Any]] = None,
    **costs: float,
) -> MKATaskCost:
    """記錄單一任務成本；total 自動加總。"""
    payload = {key: float(costs.get(key, 0.0) or 0.0) for key in _COST_FIELDS}
    row = MKATaskCost(
        tenant_id=tenant_id,
        task_type=task_type,
        task_id=task_id,
        correlation_id=correlation_id,
        total_cost=sum(payload.values()),
        details=details or {},
        **payload,
    )
    db.add(row)
    db.flush()
    return row


def get_cost_summary_db(
    db: Session,
    tenant_id: UUID,
    *,
    task_type: Optional[str] = None,
    limit: int = 10000,
) -> Dict[str, Any]:
    """租戶成本摘要（DB 聚合，非記憶體）。"""
    query = db.query(MKATaskCost).filter(MKATaskCost.tenant_id == tenant_id)
    if task_type:
        query = query.filter(MKATaskCost.task_type == task_type)
    records = query.order_by(MKATaskCost.created_at.desc()).limit(limit).all()
    if not records:
        return {"tenant_id": str(tenant_id), "total_tasks": 0, "total_cost": 0.0}
    total = sum(r.total_cost or 0.0 for r in records)
    return {
        "tenant_id": str(tenant_id),
        "total_tasks": len(records),
        "total_cost": total,
        "avg_cost_per_task": total / len(records),
        "cost_breakdown": {
            key.replace("_cost", ""): sum(getattr(r, key) or 0.0 for r in records)
            for key in _COST_FIELDS
        },
    }


def purge_expired_transcripts(
    db: Session, *, now: Optional[datetime] = None
) -> Dict[str, Any]:
    """硬刪超過租戶保留期的 InteractionSession（含 transcript）。

    每個租戶套用自己的 transcript_retention_days；無政策記錄的租戶用預設 365 天。
    回傳刪除統計供 audit。

    註：統一用 naive UTC 比較，相容 SQLite（無 tz）與 Postgres timestamptz。
    """
    if now is None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
    elif now.tzinfo is not None:
        now = now.replace(tzinfo=None)
    default_days = AudioRetentionPolicy().transcript_retention_days
    policies = db.query(MKAAudioPolicy).all()
    days_by_tenant = {
        row.tenant_id: int(row.transcript_retention_days or default_days)
        for row in policies
    }
    tenant_ids = [row[0] for row in db.query(InteractionSession.tenant_id).distinct()]
    deleted = 0
    per_tenant: Dict[str, int] = {}
    for tid in tenant_ids:
        cutoff = now - timedelta(days=days_by_tenant.get(tid, default_days))
        count = (
            db.query(InteractionSession)
            .filter(
                InteractionSession.tenant_id == tid,
                InteractionSession.created_at < cutoff,
            )
            .delete(synchronize_session=False)
        )
        per_tenant[str(tid)] = count
        deleted += count
    db.flush()
    logger.info("MKA retention purge: deleted=%d tenants=%d", deleted, len(tenant_ids))
    return {"deleted_sessions": deleted, "tenants_scanned": len(tenant_ids), "per_tenant": per_tenant}