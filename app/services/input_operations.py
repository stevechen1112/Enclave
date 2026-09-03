"""Input capacity admission, fair scheduling, SLO and reconciliation controls."""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
import logging
from math import ceil
from typing import Any
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.asset import AssetRevision, SourceAsset
from app.models.ingestion import IngestionJob, InputOperationMetric
from app.models.outbox import DeadLetterEvent
from app.services.capacity_gate import load_capacity_spec

ACTIVE_JOB_STATES = ("queued", "running")
TERMINAL_JOB_STATES = ("ready", "review_required", "failed", "cancelled")
logger = logging.getLogger(__name__)


def profile_name(value: str | None) -> str:
    name = str(value or "standard").strip().lower()
    return name if name in {"lite", "standard", "enterprise"} else "standard"


def onboarding_quota_template(profile: str) -> dict[str, Any]:
    name = profile_name(profile)
    spec = load_capacity_spec()["profiles"][name]
    queue_depth = int(spec["resource_limits"]["queue_depth"])
    peak = spec["expected_peak"]
    return {
        "profile": name,
        "max_active_ingestion_jobs_per_tenant": max(1, queue_depth // 5),
        "global_queue_depth": queue_depth,
        "ingest_jobs_per_hour": int(peak["ingest_jobs_per_hour"]),
        "media_hours_per_day": float(peak["media_hours_per_day"]),
        "monthly_cost_limit_usd": {
            "lite": 100.0,
            "standard": 1000.0,
            "enterprise": 5000.0,
        }[name],
        "status": "onboarding_default_not_commercial_commitment",
    }


def estimate_capacity(
    *,
    ingest_jobs_per_hour: int,
    media_hours_per_day: float,
    storage_gb: float,
    audio_hours_per_month: float = 0,
    video_hours_per_month: float = 0,
) -> dict[str, Any]:
    spec = load_capacity_spec()
    recommended = None
    for name in ("lite", "standard", "enterprise"):
        peak = spec["profiles"][name]["expected_peak"]
        if (
            ingest_jobs_per_hour <= int(peak["ingest_jobs_per_hour"])
            and media_hours_per_day <= float(peak["media_hours_per_day"])
        ):
            recommended = name
            break
    units = spec["cost_units"]
    modeled_cost = (
        max(0.0, storage_gb) * float(units["storage_gb_month"])
        + max(0.0, audio_hours_per_month) * float(units["audio_hour"])
        + max(0.0, video_hours_per_month) * float(units["video_hour"])
    )
    return {
        "recommended_profile": recommended,
        "within_published_internal_profiles": recommended is not None,
        "modeled_monthly_input_cost_usd": round(modeled_cost, 2),
        "quota_template": onboarding_quota_template(recommended or "enterprise"),
        "claim_boundary": "Planning estimate only; live I7 evidence is required for a commitment.",
    }


def admission_decision(
    db: Session,
    *,
    tenant_id: UUID,
    profile: str,
) -> dict[str, Any]:
    template = onboarding_quota_template(profile)
    tenant_active = db.query(IngestionJob).filter(
        IngestionJob.tenant_id == tenant_id,
        IngestionJob.status.in_(ACTIVE_JOB_STATES),
    ).count()
    global_active = db.query(IngestionJob).filter(
        IngestionJob.status.in_(ACTIVE_JOB_STATES)
    ).count()
    tenant_limit = int(template["max_active_ingestion_jobs_per_tenant"])
    global_limit = int(template["global_queue_depth"])
    allowed = tenant_active < tenant_limit and global_active < global_limit
    reason = (
        "tenant_backpressure"
        if tenant_active >= tenant_limit
        else "global_backpressure"
        if global_active >= global_limit
        else "admitted"
    )
    result = {
        "allowed": allowed,
        "reason": reason,
        "tenant_active": tenant_active,
        "tenant_limit": tenant_limit,
        "global_active": global_active,
        "global_limit": global_limit,
        "retry_after_seconds": 30 if not allowed else None,
    }
    from app.observability.business_metrics import record_input_admission

    record_input_admission(reason=reason)
    return result


def fair_job_order(
    db: Session, *, limit: int = 100, scan_limit: int = 5000
) -> list[IngestionJob]:
    """Round-robin oldest queued jobs so one tenant cannot monopolize dispatch."""

    rows = db.query(IngestionJob).filter(
        IngestionJob.status == "queued"
    ).order_by(IngestionJob.created_at, IngestionJob.id).limit(scan_limit).all()
    queues: dict[UUID, deque[IngestionJob]] = defaultdict(deque)
    tenant_order: list[UUID] = []
    for row in rows:
        if row.tenant_id not in queues:
            tenant_order.append(row.tenant_id)
        queues[row.tenant_id].append(row)
    selected: list[IngestionJob] = []
    while tenant_order and len(selected) < max(0, limit):
        next_order: list[UUID] = []
        for tenant_id in tenant_order:
            queue = queues[tenant_id]
            if queue and len(selected) < limit:
                selected.append(queue.popleft())
            if queue:
                next_order.append(tenant_id)
        tenant_order = next_order
    return selected


def record_input_metric(
    db: Session,
    *,
    tenant_id: UUID,
    journey: str,
    phase: str,
    workload_kind: str,
    outcome: str,
    duration_ms: int,
    correlation_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> InputOperationMetric | None:
    row = InputOperationMetric(
        tenant_id=tenant_id,
        journey=journey,
        phase=phase,
        workload_kind=workload_kind,
        outcome=outcome,
        duration_ms=max(0, int(duration_ms)),
        correlation_id=correlation_id,
        details=dict(details or {}),
    )
    try:
        # Telemetry must never abort the caller's business transaction during a
        # rolling deployment or a degraded observability store.  A savepoint
        # isolates the metric insert while preserving already-flushed job state.
        with db.begin_nested():
            db.add(row)
            db.flush([row])
    except SQLAlchemyError as exc:
        logger.warning(
            "input operation metric write skipped",
            extra={
                "tenant_id": str(tenant_id),
                "journey": journey,
                "phase": phase,
                "error_type": type(exc).__name__,
            },
        )
        return None
    from app.observability.business_metrics import record_input_phase

    record_input_phase(
        journey=journey,
        phase=phase,
        outcome=outcome,
        duration_ms=row.duration_ms,
    )
    return row


def _percentile(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, ceil(percentile * len(ordered)) - 1)]


def input_slo_dashboard(
    db: Session,
    *,
    tenant_id: UUID,
    profile: str,
    since: datetime | None = None,
) -> dict[str, Any]:
    start = since or datetime.now(timezone.utc) - timedelta(days=30)
    rows = db.query(InputOperationMetric).filter(
        InputOperationMetric.tenant_id == tenant_id,
        InputOperationMetric.recorded_at >= start,
    ).all()
    grouped: dict[str, list[int]] = defaultdict(list)
    outcomes: dict[str, int] = defaultdict(int)
    for row in rows:
        grouped[row.phase].append(int(row.duration_ms))
        outcomes[row.outcome] += 1
    phases = {
        phase: {
            "count": len(values),
            "p50_ms": _percentile(values, 0.5),
            "p95_ms": _percentile(values, 0.95),
        }
        for phase, values in grouped.items()
    }
    spec = load_capacity_spec()["profiles"][profile_name(profile)]["slo"]
    return {
        "tenant_id": str(tenant_id),
        "profile": profile_name(profile),
        "window_start": start.isoformat(),
        "sample_count": len(rows),
        "phases": phases,
        "outcomes": dict(outcomes),
        "targets": {
            "upload_p95_ms": spec["upload_p95_ms"],
            "ingest_lag_p95_seconds": spec["ingest_lag_p95_seconds"],
        },
        "evidence_state": "LIVE" if rows else "NOT_MEASURED",
    }


def reconcile_stale_ingestion_jobs(
    db: Session,
    *,
    tenant_id: UUID,
    stale_before: datetime,
    max_attempts: int = 3,
) -> dict[str, Any]:
    """Requeue recoverable stale jobs and dead-letter exhausted jobs."""

    from app.services.ingestion_orchestrator import get_ingestion_orchestrator

    last_activity = func.coalesce(
        IngestionJob.updated_at,
        IngestionJob.started_at,
        IngestionJob.created_at,
    )
    jobs = db.query(IngestionJob).filter(
        IngestionJob.tenant_id == tenant_id,
        IngestionJob.status == "running",
        last_activity < stale_before,
    ).with_for_update().all()
    requeued = 0
    dead_lettered = 0
    requeued_job_ids: list[str] = []
    orchestrator = get_ingestion_orchestrator()
    for job in jobs:
        if int(job.attempt or 0) < max_attempts:
            orchestrator.transition(
                db,
                job,
                to_status="queued",
                phase="reconciled_retry",
                details={"reason": "stale_worker", "previous_attempt": job.attempt},
            )
            revision = db.query(AssetRevision).filter(
                AssetRevision.tenant_id == tenant_id,
                AssetRevision.id == job.asset_revision_id,
            ).first()
            if revision is not None:
                revision.ingestion_status = "queued"
                asset = db.query(SourceAsset).filter(
                    SourceAsset.tenant_id == tenant_id,
                    SourceAsset.id == revision.asset_id,
                ).first()
                if asset is not None:
                    asset.status = "processing"
            requeued += 1
            requeued_job_ids.append(str(job.id))
            continue
        exists = db.query(DeadLetterEvent).filter(
            DeadLetterEvent.tenant_id == tenant_id,
            DeadLetterEvent.original_event_id == job.id,
            DeadLetterEvent.aggregate_type == "ingestion_job",
        ).first()
        orchestrator.fail(
            db,
            job,
            code="retry_exhausted",
            message="stale ingestion job exceeded retry limit",
            phase="dead_lettered",
            category="resource",
            retryable=False,
            user_message="處理程序中斷且已達安全重試上限，請由管理員重新處理。",
        )
        revision = db.query(AssetRevision).filter(
            AssetRevision.tenant_id == tenant_id,
            AssetRevision.id == job.asset_revision_id,
        ).first()
        if revision is not None:
            revision.ingestion_status = "failed"
            asset = db.query(SourceAsset).filter(
                SourceAsset.tenant_id == tenant_id,
                SourceAsset.id == revision.asset_id,
            ).first()
            if asset is not None:
                asset.status = "failed"
        if exists is None:
            db.add(
                DeadLetterEvent(
                    tenant_id=tenant_id,
                    original_event_id=job.id,
                    aggregate_type="ingestion_job",
                    aggregate_id=str(job.id),
                    event_type="ingestion_retry_exhausted",
                    reason="stale_worker_retry_exhausted",
                    payload={"asset_revision_id": str(job.asset_revision_id)},
                    attempts=int(job.attempt or 0),
                )
            )
        dead_lettered += 1
    db.flush()
    return {
        "scanned": len(jobs),
        "requeued": requeued,
        "dead_lettered": dead_lettered,
        "requeued_job_ids": requeued_job_ids,
    }
