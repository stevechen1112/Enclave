"""Tenant-scoped P5 cost units, reporting and fail-closed reservations."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.asset import AssetRevision, SourceAsset
from app.models.audit import UsageRecord
from app.models.document import Document
from app.models.mka import MKATaskCost
from app.models.tenant import Tenant
from app.services.capacity_gate import load_capacity_spec


class MediaDurationError(ValueError):
    pass


def probe_media_duration_ms(path: str) -> int:
    """Read audio/video duration with the same ffprobe dependency as video ingest."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MediaDurationError("media duration probe unavailable") from exc
    if result.returncode != 0:
        raise MediaDurationError("media duration probe rejected the file")
    try:
        duration_ms = round(
            float(json.loads(result.stdout)["format"]["duration"]) * 1000
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise MediaDurationError("media duration metadata is invalid") from exc
    if duration_ms <= 0:
        raise MediaDurationError("media duration must be positive")
    return duration_ms


def _month_start(now: datetime | None = None) -> datetime:
    current = now or datetime.now(UTC)
    return current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


@lru_cache(maxsize=1)
def _cached_cost_units() -> tuple[tuple[str, float], ...]:
    return tuple(
        sorted(
            (key, float(value))
            for key, value in load_capacity_spec()["cost_units"].items()
        )
    )


def cost_units() -> dict[str, float]:
    return dict(_cached_cost_units())


def media_cost_usd(kind: str, duration_ms: int) -> float:
    if kind not in {"audio", "video"}:
        raise ValueError(f"unsupported media cost kind: {kind}")
    duration_hours = max(0, int(duration_ms)) / 3_600_000
    return round(duration_hours * cost_units()[f"{kind}_hour"], 6)


def query_reservation_cost_usd() -> float:
    return round(cost_units()["queries_1000"] / 1000, 6)


def current_monthly_cost_usd(
    db: Session, tenant_id: UUID, *, now: datetime | None = None
) -> float:
    start = _month_start(now)
    usage = (
        db.query(func.coalesce(func.sum(UsageRecord.estimated_cost_usd), 0))
        .filter(UsageRecord.tenant_id == tenant_id, UsageRecord.created_at >= start)
        .scalar()
        or 0
    )
    tasks = (
        db.query(func.coalesce(func.sum(MKATaskCost.total_cost), 0))
        .filter(MKATaskCost.tenant_id == tenant_id, MKATaskCost.created_at >= start)
        .scalar()
        or 0
    )
    return round(float(usage) + float(tasks), 6)


def check_cost_guardrail(
    db: Session, tenant_id: UUID, *, additional_cost_usd: float = 0.0
) -> dict[str, Any]:
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        return {"allowed": False, "message": "租戶不存在", "axis": "cost"}
    current = current_monthly_cost_usd(db, tenant_id)
    limit = tenant.monthly_cost_limit_usd
    projected = current + max(0.0, float(additional_cost_usd))
    if limit is not None and projected > float(limit):
        return {
            "allowed": False,
            "message": (
                f"月成本已達上限 USD {limit:.2f}，預估本次後為 USD {projected:.2f}"
            ),
            "axis": "cost",
            "current": current,
            "limit": float(limit),
            "projected": round(projected, 6),
        }
    return {
        "allowed": True,
        "message": "OK",
        "axis": "cost",
        "current": current,
        "limit": float(limit) if limit is not None else None,
        "projected": round(projected, 6),
    }


def reserve_media_cost(
    db: Session,
    *,
    tenant_id: UUID,
    media_kind: str,
    duration_ms: int,
    task_id: str,
) -> dict[str, Any]:
    locked = db.query(Tenant).filter(Tenant.id == tenant_id).with_for_update().first()
    if locked is None:
        return {"allowed": False, "message": "租戶不存在", "axis": "cost"}
    estimate = media_cost_usd(media_kind, duration_ms)
    result = check_cost_guardrail(db, tenant_id, additional_cost_usd=estimate)
    if not result["allowed"]:
        return result
    row = MKATaskCost(
        tenant_id=tenant_id,
        task_type=f"{media_kind}_ingest_reservation",
        task_id=task_id,
        stt_cost=estimate if media_kind == "audio" else 0.0,
        ocr_cost=estimate if media_kind == "video" else 0.0,
        total_cost=estimate,
        details={
            "basis": f"{media_kind}_hour",
            "duration_ms": int(duration_ms),
            "rate_usd": cost_units()[f"{media_kind}_hour"],
            "reservation": True,
        },
    )
    db.add(row)
    db.flush()
    return {
        **result,
        "reserved_cost_usd": estimate,
        "reservation_id": str(row.id),
    }


def build_tenant_cost_report(
    db: Session, tenant_id: UUID, *, now: datetime | None = None
) -> dict[str, Any]:
    start = _month_start(now)
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        raise ValueError("tenant not found")
    current_revisions = (
        db.query(AssetRevision)
        .join(
            SourceAsset,
            (SourceAsset.tenant_id == AssetRevision.tenant_id)
            & (SourceAsset.id == AssetRevision.asset_id)
            & (SourceAsset.current_revision == AssetRevision.revision),
        )
        .filter(
            SourceAsset.tenant_id == tenant_id,
            SourceAsset.tombstoned_at.is_(None),
        )
    )
    storage_bytes = int(
        current_revisions.with_entities(
            func.coalesce(func.sum(AssetRevision.byte_size), 0)
        ).scalar()
        or 0
    )
    # Legacy documents without a canonical SourceAsset projection still consume
    # storage. Projected rows are excluded because their bytes are counted above.
    storage_bytes += int(
        db.query(func.coalesce(func.sum(Document.file_size), 0))
        .filter(
            Document.tenant_id == tenant_id,
            Document.tombstoned_at.is_(None),
            Document.source_asset_id.is_(None),
        )
        .scalar()
        or 0
    )

    def _duration(kind: str) -> int:
        return int(
            current_revisions.filter(
                SourceAsset.asset_kind == kind,
                AssetRevision.created_at >= start,
            )
            .with_entities(func.coalesce(func.sum(AssetRevision.duration_ms), 0))
            .scalar()
            or 0
        )

    query_count = int(
        db.query(func.count(UsageRecord.id))
        .filter(
            UsageRecord.tenant_id == tenant_id,
            UsageRecord.created_at >= start,
            UsageRecord.action_type.in_(("chat", "chat_query")),
        )
        .scalar()
        or 0
    )
    units = cost_units()
    raw_rows = (
        ("storage_gb_month", storage_bytes / (1024**3)),
        ("audio_hour", _duration("audio") / 3_600_000),
        ("video_hour", _duration("video") / 3_600_000),
        ("queries_1000", query_count / 1000),
    )
    unit_reports = [
        {
            "unit": unit,
            "usage": round(usage, 6),
            "rate_usd": units[unit],
            "estimated_cost_usd": round(usage * units[unit], 6),
        }
        for unit, usage in raw_rows
    ]
    tracked = current_monthly_cost_usd(db, tenant_id, now=now)
    limit = tenant.monthly_cost_limit_usd
    return {
        "tenant_id": str(tenant_id),
        "period_start": start.isoformat(),
        "currency": "USD",
        "tracked_cost_usd": tracked,
        "modeled_cost_usd": round(
            sum(row["estimated_cost_usd"] for row in unit_reports), 6
        ),
        "monthly_cost_limit_usd": float(limit) if limit is not None else None,
        "cost_usage_ratio": round(tracked / limit, 6) if limit else None,
        "guardrail_state": (
            "blocked" if limit is not None and tracked >= limit else "open"
        ),
        "unit_reports": unit_reports,
    }
