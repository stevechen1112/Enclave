"""
MKA-P6：企業系統整合與有限自動化 — write 護欄（DB-backed）。

對照 ENGINEERING_PLAN.md §8 MKA-P6：
順序：read-only 查詢 → 資料預填 → 核准後 low-risk write → 高風險寫入保持人工
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


class WriteRisk(str, Enum):
    READ_ONLY = "read_only"
    LOW_RISK_WRITE = "low_risk_write"
    HIGH_RISK_WRITE = "high_risk_write"
    PROHIBITED = "prohibited"


class WriteStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    EXECUTING = "executing"
    SUCCESS = "success"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    RETRYING = "retrying"


@dataclass
class WriteRequest:
    """企業系統寫入請求。"""
    request_id: str = ""
    correlation_id: str = ""
    idempotency_key: str = ""
    target_system: str = ""
    operation: str = ""
    risk: WriteRisk = WriteRisk.READ_ONLY
    payload: Dict[str, Any] = field(default_factory=dict)
    payload_hash: str = ""
    approval_token: str = ""
    approval_required: bool = True
    max_retries: int = 3
    retry_count: int = 0
    status: WriteStatus = WriteStatus.PENDING
    result: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    initiated_by: str = ""
    initiated_at: str = ""
    executed_at: str = ""
    rolled_back_at: str = ""
    tenant_id: str = ""

    def __post_init__(self):
        if not self.request_id:
            self.request_id = str(uuid4())
        if not self.correlation_id:
            self.correlation_id = str(uuid4())
        if not self.idempotency_key:
            self.idempotency_key = self._compute_hash()
        if not self.payload_hash:
            self.payload_hash = self._compute_hash()
        if isinstance(self.risk, str):
            self.risk = WriteRisk(self.risk)
        if isinstance(self.status, str):
            self.status = WriteStatus(self.status)

    def _compute_hash(self) -> str:
        content = json.dumps(self.payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
            "idempotency_key": self.idempotency_key,
            "target_system": self.target_system,
            "operation": self.operation,
            "risk": self.risk.value if isinstance(self.risk, WriteRisk) else self.risk,
            "payload_hash": self.payload_hash,
            "approval_required": self.approval_required,
            "approval_token": self.approval_token,
            "max_retries": self.max_retries,
            "retry_count": self.retry_count,
            "status": self.status.value if isinstance(self.status, WriteStatus) else self.status,
            "error": self.error,
            "initiated_by": self.initiated_by,
            "initiated_at": self.initiated_at,
            "executed_at": self.executed_at,
            "rolled_back_at": self.rolled_back_at,
            "result": self.result,
        }


class WriteGuardrail:
    """寫入護欄 — 記憶體＋可選 DB 持久化。"""

    def __init__(self, db: Any = None, tenant_id: Optional[UUID] = None):
        self.db = db
        self.tenant_id = tenant_id
        self._executed_keys: Dict[str, WriteRequest] = {}
        self._audit_log: List[Dict[str, Any]] = []

    def validate(self, request: WriteRequest) -> Tuple[bool, str]:
        if request.risk == WriteRisk.PROHIBITED:
            self._audit(request, "rejected", "prohibited operation")
            return False, "Operation is prohibited"

        existing = self._lookup_idempotent(request)
        if existing is not None:
            if existing.status == WriteStatus.SUCCESS:
                self._audit(request, "idempotent_skip", "already executed successfully")
                return True, f"Idempotent skip (already executed: {existing.request_id})"
            if existing.payload_hash != request.payload_hash:
                self._audit(request, "rejected", "payload hash mismatch on same idempotency key")
                return False, "Payload hash mismatch on same idempotency key"

        if request.risk == WriteRisk.HIGH_RISK_WRITE and request.approval_required:
            if not request.approval_token:
                self._audit(request, "rejected", "high-risk write without approval token")
                return False, "High-risk write requires approval token"

        if request.max_retries > 5:
            return False, "max_retries exceeds limit (5)"

        self._audit(request, "validated", "passed all guardrails")
        return True, "validated"

    def execute(
        self,
        request: WriteRequest,
        execute_fn: Any,
        rollback_fn: Any = None,
    ) -> WriteRequest:
        valid, reason = self.validate(request)
        if not valid:
            request.status = WriteStatus.FAILED
            request.error = reason
            self._persist(request)
            return request

        # idempotent short-circuit
        if reason.startswith("Idempotent skip"):
            existing = self._lookup_idempotent(request)
            if existing:
                return existing

        request.status = WriteStatus.EXECUTING
        request.initiated_at = datetime.now(timezone.utc).isoformat()
        self._persist(request)

        for attempt in range(request.max_retries + 1):
            request.retry_count = attempt
            try:
                result = execute_fn(request.payload)
                request.result = result if isinstance(result, dict) else {"result": str(result)}
                request.status = WriteStatus.SUCCESS
                request.executed_at = datetime.now(timezone.utc).isoformat()
                self._executed_keys[request.idempotency_key] = request
                self._audit(request, "success", f"executed on attempt {attempt}")
                self._persist(request)
                return request
            except Exception as exc:
                logger.warning("Write attempt %s failed: %s", attempt, exc)
                request.error = str(exc)
                if attempt < request.max_retries:
                    request.status = WriteStatus.RETRYING
                    self._audit(request, "retrying", f"attempt {attempt} failed: {exc}")
                    self._persist(request)
                else:
                    if rollback_fn:
                        try:
                            rollback_fn(request.payload, request.result)
                            request.status = WriteStatus.ROLLED_BACK
                            request.rolled_back_at = datetime.now(timezone.utc).isoformat()
                            self._audit(request, "rolled_back", f"rollback after {attempt+1} attempts")
                        except Exception as rb_exc:
                            logger.error("Rollback failed: %s", rb_exc)
                            request.status = WriteStatus.FAILED
                            self._audit(request, "rollback_failed", str(rb_exc))
                    else:
                        request.status = WriteStatus.FAILED
                        self._audit(request, "failed", f"all {attempt+1} attempts failed: {exc}")
                    self._persist(request)
                    return request

        request.status = WriteStatus.FAILED
        self._persist(request)
        return request

    def get_audit_log(self, correlation_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if self.db is not None and self.tenant_id is not None:
            from app.models.mka import MKAWriteAudit
            q = self.db.query(MKAWriteAudit).filter(MKAWriteAudit.tenant_id == self.tenant_id)
            if correlation_id:
                q = q.filter(MKAWriteAudit.correlation_id == correlation_id)
            rows = q.order_by(MKAWriteAudit.created_at.desc()).limit(200).all()
            return [
                {
                    "correlation_id": r.correlation_id,
                    "request_id": r.request_id,
                    "event": r.event,
                    "detail": r.detail,
                    "timestamp": r.created_at.isoformat() if r.created_at else None,
                    "target_system": r.target_system,
                    "risk": r.risk,
                }
                for r in rows
            ]
        if correlation_id:
            return [e for e in self._audit_log if e.get("correlation_id") == correlation_id]
        return list(self._audit_log)

    def _lookup_idempotent(self, request: WriteRequest) -> Optional[WriteRequest]:
        if request.idempotency_key in self._executed_keys:
            return self._executed_keys[request.idempotency_key]
        if self.db is None or self.tenant_id is None:
            return None
        from app.models.mka import MKAWriteRequest
        row = (
            self.db.query(MKAWriteRequest)
            .filter(
                MKAWriteRequest.tenant_id == self.tenant_id,
                MKAWriteRequest.idempotency_key == request.idempotency_key,
            )
            .first()
        )
        if row is None:
            return None
        return WriteRequest(
            request_id=row.request_id,
            correlation_id=row.correlation_id,
            idempotency_key=row.idempotency_key,
            target_system=row.target_system,
            operation=row.operation,
            risk=WriteRisk(row.risk),
            payload=row.payload or {},
            payload_hash=row.payload_hash,
            approval_token=row.approval_token or "",
            approval_required=bool(row.approval_required),
            max_retries=row.max_retries or 3,
            retry_count=row.retry_count or 0,
            status=WriteStatus(row.status),
            result=row.result or {},
            error=row.error or "",
            initiated_by=str(row.initiated_by or ""),
            tenant_id=str(row.tenant_id),
        )

    def _persist(self, request: WriteRequest) -> None:
        if self.db is None or self.tenant_id is None:
            return
        from app.models.mka import MKAWriteRequest

        row = (
            self.db.query(MKAWriteRequest)
            .filter(
                MKAWriteRequest.tenant_id == self.tenant_id,
                MKAWriteRequest.request_id == request.request_id,
            )
            .first()
        )
        if row is None:
            row = MKAWriteRequest(
                tenant_id=self.tenant_id,
                request_id=request.request_id,
                correlation_id=request.correlation_id,
                idempotency_key=request.idempotency_key,
                target_system=request.target_system,
                operation=request.operation,
                risk=request.risk.value,
                payload=request.payload,
                payload_hash=request.payload_hash,
            )
            self.db.add(row)
        row.approval_token = request.approval_token or None
        row.approval_required = request.approval_required
        row.status = request.status.value
        row.result = request.result or {}
        row.error = request.error or None
        row.retry_count = request.retry_count
        row.max_retries = request.max_retries
        if request.initiated_by:
            try:
                row.initiated_by = UUID(request.initiated_by)
            except Exception:
                pass
        self.db.flush()

    def _audit(self, request: WriteRequest, event: str, detail: str) -> None:
        entry = {
            "correlation_id": request.correlation_id,
            "request_id": request.request_id,
            "event": event,
            "detail": detail,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "target_system": request.target_system,
            "risk": request.risk.value if isinstance(request.risk, WriteRisk) else request.risk,
        }
        self._audit_log.append(entry)
        if self.db is None or self.tenant_id is None:
            return
        from app.models.mka import MKAWriteAudit
        self.db.add(
            MKAWriteAudit(
                tenant_id=self.tenant_id,
                correlation_id=request.correlation_id,
                request_id=request.request_id,
                event=event,
                detail=detail,
                target_system=request.target_system,
                risk=entry["risk"],
            )
        )
        try:
            self.db.flush()
        except Exception:
            pass


_guardrail: Optional[WriteGuardrail] = None


def get_write_guardrail(db: Any = None, tenant_id: Optional[UUID] = None) -> WriteGuardrail:
    if db is not None:
        return WriteGuardrail(db=db, tenant_id=tenant_id)
    global _guardrail
    if _guardrail is None:
        _guardrail = WriteGuardrail()
    return _guardrail
