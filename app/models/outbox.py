"""
Phase 0 — Event Sourcing & Consistency Infrastructure

提供跨服務的最終一致性保證：
  - OutboxEvent：交易性事件發佈（與業務資料同一交易提交）
  - ProjectionStatus：追蹤每個 downstream projection 的收斂狀態
  - SyncCursor：Connector 增量同步游標
  - DeadLetterEvent：失敗事件不丟失
"""
import uuid
from sqlalchemy import (
    Column, String, Integer, DateTime, ForeignKey, func,
    Text, JSON, Index,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base_class import Base


# ═══════════════════════════════════════════════════════════════════════════════
#  OutboxEvent
# ═══════════════════════════════════════════════════════════════════════════════

class OutboxEvent(Base):
    """
    交易性 Outbox — 與業務資料在同一 DB 交易中提交。

    每個事件代表一個需要傳播到下游的狀態變更：
      - document.created / document.updated / document.deleted
      - permission.changed / permission.revoked
      - kb.revision_updated
      - tenant.suspended
    """

    __tablename__ = "outbox_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    aggregate_type = Column(String, nullable=False, index=True)  # document | permission | kb | tenant
    aggregate_id = Column(String, nullable=False, index=True)    # UUID of the changed entity
    event_type = Column(String, nullable=False)                   # created | updated | deleted | revoked
    revision = Column(Integer, nullable=False)                    # monotonic revision number
    payload = Column(JSON, nullable=False, default=dict)          # event payload
    idempotency_key = Column(String, nullable=False, unique=True, index=True)
    status = Column(String, default="pending")  # pending | processing | completed | failed
    attempts = Column(Integer, default=0)
    next_retry_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


# ═══════════════════════════════════════════════════════════════════════════════
#  ProjectionStatus
# ═══════════════════════════════════════════════════════════════════════════════

class ProjectionStatus(Base):
    """
    追蹤每個 downstream projection 的收斂狀態。

    每個 resource（document/wiki/graph entity）在每個 provider 都有一行，
    記錄 desired_revision（Canonical Store 的最新版本）與
    applied_revision（downstream 實際應用的版本）。
    """

    __tablename__ = "projection_status"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    resource_type = Column(String, nullable=False)  # document | chunk | wiki_page | graph_entity
    resource_id = Column(String, nullable=False, index=True)
    provider = Column(String, nullable=False)  # ragflow | weknora | pipeshub
    provider_instance_id = Column(String, nullable=True)
    desired_revision = Column(Integer, nullable=False)
    applied_revision = Column(Integer, nullable=False, default=0)
    state = Column(String, default="pending")  # pending | in_progress | converged | diverged | error
    last_error = Column(Text, nullable=True)
    last_verified_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        # NULLS NOT DISTINCT enforced in migration p1_dd_m04
        Index(
            "ix_projection_status_resource_provider",
            "resource_type",
            "resource_id",
            "provider",
            "provider_instance_id",
        ),
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  SyncCursor
# ═══════════════════════════════════════════════════════════════════════════════

class SyncCursor(Base):
    """
    Connector 增量同步游標。

    每個 connector instance 保存其最後成功同步的位置，
    用於增量同步（delta sync）與斷點續傳。
    """

    __tablename__ = "sync_cursors"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    connector_instance_id = Column(String, nullable=False, unique=True, index=True)
    connector_type = Column(String, nullable=False)  # google_drive | sharepoint | nas_smb | ...
    cursor = Column(Text, nullable=True)  # opaque cursor from source system
    watermark = Column(DateTime(timezone=True), nullable=True)  # last synced event timestamp
    last_success_at = Column(DateTime(timezone=True), nullable=True)
    sync_state = Column(JSON, default=dict)  # additional state (e.g., page tokens)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


# ═══════════════════════════════════════════════════════════════════════════════
#  DeadLetterEvent
# ═══════════════════════════════════════════════════════════════════════════════

class DeadLetterEvent(Base):
    """
    失敗事件不丟失 — 超過最大重試次數的 outbox event 移到這裡。
    """

    __tablename__ = "dead_letter_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    original_event_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    aggregate_type = Column(String, nullable=False)
    aggregate_id = Column(String, nullable=False)
    event_type = Column(String, nullable=False)
    reason = Column(Text, nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    attempts = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
