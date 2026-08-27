"""Outbox event publish helpers (no Celery import — avoids circular deps)."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.outbox import OutboxEvent


def publish_event(
    db: Session,
    aggregate_type: str,
    aggregate_id: str,
    event_type: str,
    revision: int,
    payload: dict,
    tenant_id: UUID | str | None = None,
    idempotency_key: Optional[str] = None,
) -> OutboxEvent:
    """
    確定性冪等鍵：同一 aggregate/event/revision 重送不得產生第二筆。
    """
    resolved_tenant = tenant_id or payload.get("tenant_id")
    try:
        resolved_tenant = UUID(str(resolved_tenant))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("outbox events require an explicit tenant_id") from exc
    payload = {**payload, "tenant_id": str(resolved_tenant)}
    if idempotency_key is None:
        idempotency_key = f"{aggregate_type}:{aggregate_id}:{event_type}:{revision}"

    existing = (
        db.query(OutboxEvent)
        .filter(
            OutboxEvent.tenant_id == resolved_tenant,
            OutboxEvent.idempotency_key == idempotency_key,
        )
        .first()
    )
    if existing:
        return existing

    event = OutboxEvent(
        tenant_id=resolved_tenant,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event_type,
        revision=revision,
        payload=payload,
        idempotency_key=idempotency_key,
        status="pending",
    )
    db.add(event)
    return event
