"""Phase 0/1 — Projection reconciliation jobs."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.models.outbox import ProjectionStatus
from app.gateway.adapter_factory import build_projection_adapters

logger = logging.getLogger(__name__)


def reconcile_diverged_projections(db: Session, batch_size: int = 50) -> Dict[str, Any]:
    rows = (
        db.query(ProjectionStatus)
        .filter(ProjectionStatus.state.in_(["pending", "diverged", "error"]))
        .order_by(ProjectionStatus.updated_at)
        .limit(batch_size)
        .all()
    )
    adapters = build_projection_adapters()
    reconciled = 0
    errors: List[str] = []

    for row in rows:
        adapter = adapters.get(row.provider)
        if not adapter:
            continue
        try:
            result = asyncio.run(
                adapter.reconcile(row.resource_type, row.resource_id, row.desired_revision)
            )
            if result.get("converged"):
                row.state = "converged"
                row.applied_revision = result.get("current_revision", row.desired_revision)
                row.last_error = None
            else:
                row.state = "diverged"
            row.last_verified_at = datetime.now(timezone.utc)
            reconciled += 1
        except Exception as exc:
            row.state = "error"
            row.last_error = str(exc)[:500]
            errors.append(f"{row.provider}:{row.resource_id}:{exc}")

    db.commit()
    return {"reconciled": reconciled, "errors": errors}
