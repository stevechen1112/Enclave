"""Common ingestion lifecycle and capability routing."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
import os
from typing import Any
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.asset import AssetRevision, SourceAsset
from app.models.ingestion import IngestionJob, IngestionJobEvent
from app.platform.ingestion import IngestionAdapterRegistry, IngestionRequest

_TRANSITIONS = {
    "queued": {"running", "cancelled"},
    "running": {"queued", "running", "review_required", "ready", "failed", "cancelled"},
    "failed": {"running", "cancelled"},
    "review_required": {"ready", "failed", "cancelled"},
    "ready": set(),
    "cancelled": set(),
}


class InvalidIngestionTransition(RuntimeError):
    pass


class IngestionBackpressure(RuntimeError):
    def __init__(self, decision: dict[str, Any]):
        super().__init__(str(decision.get("reason") or "ingestion_backpressure"))
        self.decision = decision


class IngestionOrchestrator:
    def __init__(self, registry: IngestionAdapterRegistry) -> None:
        self._registry = registry

    def ensure_job(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        asset_revision_id: UUID,
        capabilities: Iterable[str],
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
        constraints: dict[str, Any] | None = None,
    ) -> IngestionJob:
        revision = (
            db.query(AssetRevision)
            .filter(
                AssetRevision.tenant_id == tenant_id,
                AssetRevision.id == asset_revision_id,
            )
            .first()
        )
        if revision is None:
            raise LookupError("asset revision not found in tenant")
        asset = (
            db.query(SourceAsset)
            .filter(
                SourceAsset.tenant_id == tenant_id,
                SourceAsset.id == revision.asset_id,
            )
            .first()
        )
        if asset is None or asset.tombstoned_at is not None:
            raise LookupError("active source asset not found in tenant")
        capability_tuple = tuple(sorted({str(item) for item in capabilities if item}))
        request = IngestionRequest(
            tenant_id=str(tenant_id),
            asset_id=str(asset.id),
            asset_revision_id=str(revision.id),
            asset_kind=asset.asset_kind,
            media_type=revision.media_type,
            content_uri=revision.content_uri,
            requested_capabilities=capability_tuple,
            constraints=constraints or {},
        )
        adapter = self._registry.select(request)
        key = idempotency_key or (
            f"{revision.id}:{adapter.adapter_key}:{','.join(capability_tuple)}"
        )
        existing = (
            db.query(IngestionJob)
            .filter(
                IngestionJob.tenant_id == tenant_id,
                IngestionJob.idempotency_key == key,
            )
            .first()
        )
        if existing is not None:
            if existing.asset_revision_id != revision.id:
                raise ValueError("idempotency key belongs to another asset revision")
            if existing.adapter_key != adapter.adapter_key or set(
                existing.requested_capabilities or []
            ) != set(capability_tuple):
                raise ValueError("idempotency key belongs to another ingestion request")
            return existing

        # Serialize tenant admission so concurrent uploads cannot all observe a
        # free slot. Global Redis depth remains the deployment-wide hard stop.
        from app.models.tenant import Tenant
        from app.services.input_operations import admission_decision

        db.query(Tenant).filter(Tenant.id == tenant_id).with_for_update().one()
        decision = admission_decision(
            db,
            tenant_id=tenant_id,
            profile=os.getenv("DEPLOYMENT_PROFILE", "standard"),
        )
        if not decision["allowed"]:
            raise IngestionBackpressure(decision)

        job = IngestionJob(
            tenant_id=tenant_id,
            asset_revision_id=revision.id,
            adapter_key=adapter.adapter_key,
            adapter_version=adapter.adapter_version,
            requested_capabilities=list(capability_tuple),
            idempotency_key=key,
            correlation_id=correlation_id,
            status="queued",
            phase="queued",
        )
        try:
            with db.begin_nested():
                db.add(job)
                db.flush()
                self._append_event(
                    db, job, from_status=None, details={"adapter": adapter.adapter_key}
                )
                db.flush()
        except IntegrityError:
            concurrent = (
                db.query(IngestionJob)
                .filter(
                    IngestionJob.tenant_id == tenant_id,
                    IngestionJob.idempotency_key == key,
                )
                .first()
            )
            if concurrent is not None and concurrent.asset_revision_id == revision.id:
                if concurrent.adapter_key != adapter.adapter_key or set(
                    concurrent.requested_capabilities or []
                ) != set(capability_tuple):
                    raise ValueError(
                        "idempotency key belongs to another ingestion request"
                    )
                return concurrent
            raise
        return job

    def transition(
        self,
        db: Session,
        job: IngestionJob,
        *,
        to_status: str,
        phase: str,
        quality_state: str | None = None,
        readiness: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        details: dict[str, Any] | None = None,
    ) -> IngestionJob:
        # Serialize state and event-sequence allocation for concurrent workers.
        locked = (
            db.query(IngestionJob)
            .filter(
                IngestionJob.tenant_id == job.tenant_id,
                IngestionJob.id == job.id,
            )
            .with_for_update()
            .one()
        )
        job = locked
        from_status = str(job.status)
        if to_status not in _TRANSITIONS.get(from_status, set()):
            raise InvalidIngestionTransition(f"{from_status} -> {to_status}")
        now = datetime.now(timezone.utc)
        job.status = to_status
        if to_status == "running" and from_status != "running":
            job.attempt = int(job.attempt or 0) + 1
            job.started_at = now
            job.completed_at = None
            self._record_phase_metric(db, job, phase="queue_wait", now=now)
        if to_status == "queued" and from_status == "running":
            job.started_at = None
            job.completed_at = None
        if to_status in {"ready", "review_required", "failed", "cancelled"}:
            job.completed_at = now
            self._record_phase_metric(db, job, phase="processing", now=now)
            self._record_phase_metric(db, job, phase="review_readiness", now=now)
        job.phase = phase
        if quality_state is not None:
            job.quality_state = quality_state
        if readiness is not None:
            job.readiness = dict(readiness)
        if error is not None:
            job.error = dict(error)
        self._append_event(db, job, from_status=from_status, details=details or {})
        db.flush()
        return job

    @staticmethod
    def _record_phase_metric(
        db: Session, job: IngestionJob, *, phase: str, now: datetime
    ) -> None:
        from app.services.input_operations import record_input_metric

        if phase == "queue_wait":
            start = job.created_at
        elif phase == "processing":
            start = job.started_at
        else:
            start = job.created_at
        if start is None:
            return
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        duration_ms = round(max(0.0, (now - start).total_seconds()) * 1000)
        kind = (
            db.query(SourceAsset.asset_kind)
            .join(
                AssetRevision,
                (AssetRevision.tenant_id == SourceAsset.tenant_id)
                & (AssetRevision.asset_id == SourceAsset.id),
            )
            .filter(
                AssetRevision.tenant_id == job.tenant_id,
                AssetRevision.id == job.asset_revision_id,
            )
            .scalar()
            or "document"
        )
        journey = kind if kind in {"audio", "video"} else "document"
        outcome = (
            "success"
            if job.status in {"ready", "review_required"}
            else "failed"
            if job.status in {"failed", "cancelled"}
            else "pending"
        )
        record_input_metric(
            db,
            tenant_id=job.tenant_id,
            journey=journey,
            phase=phase,
            workload_kind=kind if len(str(kind)) <= 32 else "document",
            outcome=outcome,
            duration_ms=duration_ms,
            correlation_id=str(job.correlation_id or job.id),
            details={"job_id": str(job.id), "attempt": int(job.attempt or 0)},
        )

    def fail(
        self,
        db: Session,
        job: IngestionJob,
        *,
        code: str,
        message: str,
        phase: str,
    ) -> IngestionJob:
        return self.transition(
            db,
            job,
            to_status="failed",
            phase=phase,
            error={"code": code, "message": str(message)[:500]},
        )

    @staticmethod
    def _append_event(
        db: Session,
        job: IngestionJob,
        *,
        from_status: str | None,
        details: dict[str, Any],
    ) -> None:
        sequence = (
            int(
                db.query(func.max(IngestionJobEvent.sequence))
                .filter(
                    IngestionJobEvent.tenant_id == job.tenant_id,
                    IngestionJobEvent.job_id == job.id,
                )
                .scalar()
                or 0
            )
            + 1
        )
        db.add(
            IngestionJobEvent(
                tenant_id=job.tenant_id,
                job_id=job.id,
                sequence=sequence,
                from_status=from_status,
                to_status=job.status,
                phase=job.phase,
                details=dict(details),
            )
        )


_orchestrator: IngestionOrchestrator | None = None


def get_ingestion_orchestrator() -> IngestionOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        from app.composition.ingestion import build_ingestion_adapter_registry

        _orchestrator = IngestionOrchestrator(build_ingestion_adapter_registry())
    return _orchestrator
