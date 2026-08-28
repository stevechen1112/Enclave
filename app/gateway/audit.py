"""
Phase 1 — Gateway Audit

Record gateway operations for compliance and observability.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.gateway.contracts import AuditTrail, GatewayError

logger = logging.getLogger(__name__)


class GatewayAuditor:
    """Persist gateway audit events."""

    def build_trail(
        self,
        operation: str,
        providers_called: List[str],
        total_latency_ms: int,
        provider_latencies: Dict[str, int],
        decisions: List[str],
        errors: Optional[List[GatewayError]] = None,
        token_usage: Optional[Dict[str, int]] = None,
    ) -> AuditTrail:
        return AuditTrail(
            operation=operation,
            providers_called=providers_called,
            total_latency_ms=total_latency_ms,
            provider_latencies=provider_latencies,
            token_usage=token_usage or {},
            decisions=decisions,
        )

    def log_operation(
        self,
        db: Optional[Session],
        tenant_id: UUID,
        subject_id: UUID,
        operation: str,
        trail: AuditTrail,
        correlation_id: Optional[str] = None,
    ) -> None:
        logger.info(
            "gateway_audit tenant=%s subject=%s op=%s providers=%s latency_ms=%d correlation=%s",
            tenant_id,
            subject_id,
            operation,
            trail.providers_called,
            trail.total_latency_ms,
            correlation_id,
        )
        if db is None:
            return
        try:
            from app.models.audit import AuditLog
            db.add(
                AuditLog(
                    tenant_id=tenant_id,
                    actor_user_id=subject_id,
                    action=f"gateway.{operation}",
                    target_type="gateway",
                    target_id=correlation_id or "",
                    detail_json={
                        "providers_called": trail.providers_called,
                        "total_latency_ms": trail.total_latency_ms,
                        "decisions": trail.decisions,
                    },
                )
            )
            db.flush()
        except Exception as exc:
            logger.warning("Failed to persist gateway audit: %s", exc)


class OperationTimer:
    """Simple latency tracker for gateway operations."""

    def __init__(self):
        self._start = time.time()
        self._provider_latencies: Dict[str, int] = {}

    def record_provider(self, provider: str, latency_ms: int) -> None:
        self._provider_latencies[provider] = latency_ms
        try:
            from app.observability.business_metrics import record_provider_call

            record_provider_call(
                provider=provider,
                duration_seconds=max(0, latency_ms) / 1000,
                ok=True,
            )
        except Exception:
            pass

    @property
    def total_latency_ms(self) -> int:
        return int((time.time() - self._start) * 1000)

    @property
    def provider_latencies(self) -> Dict[str, int]:
        return dict(self._provider_latencies)
