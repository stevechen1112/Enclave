"""Celery tasks for projection and Input lifecycle reconciliation."""

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from app.celery_app import celery_app
from app.db.session import MaintenanceSessionLocal
from app.models.outbox import ProjectionStatus
from app.services.reconciliation import reconcile_diverged_projections

logger = logging.getLogger(__name__)


@celery_app.task(name="tasks.reconcile_projections")
def reconcile_projections_batch():
    from app.services.rls import apply_rls_bypass, apply_rls_context

    db = MaintenanceSessionLocal()
    try:
        apply_rls_bypass(
            db,
            actor_identity="celery:reconcile_projections",
            operation="list_projection_tenants",
            reason="Discover tenants with diverged downstream projections",
        )
        tenant_ids = [
            row[0]
            for row in (
                db.query(ProjectionStatus.tenant_id)
                .filter(ProjectionStatus.state.in_(["pending", "diverged", "error"]))
                .distinct()
                .all()
            )
        ]
        db.commit()
        results = []
        for tenant_id in tenant_ids:
            apply_rls_context(db, tenant_id)
            results.append(
                {
                    "tenant_id": str(tenant_id),
                    **reconcile_diverged_projections(db, tenant_id=tenant_id),
                }
            )
        return {"tenants": len(results), "results": results}
    finally:
        db.close()


@celery_app.task(name="tasks.reconcile_stale_ingestion")
def reconcile_stale_ingestion_batch():
    """Recover jobs left running after a WorkerLost or host interruption."""

    from app.config import settings
    from app.models.ingestion import IngestionJob
    from app.services.ingestion_dispatch import dispatch_ingestion_job
    from app.services.ingestion_orchestrator import get_ingestion_orchestrator
    from app.services.input_operations import reconcile_stale_ingestion_jobs
    from app.services.rls import apply_rls_bypass, apply_rls_context

    db = MaintenanceSessionLocal()
    try:
        apply_rls_bypass(
            db,
            actor_identity="celery:reconcile_stale_ingestion",
            operation="list_running_ingestion_tenants",
            reason="Recover Input jobs abandoned by worker or host interruption",
        )
        tenant_ids = [
            row[0]
            for row in db.query(IngestionJob.tenant_id)
            .filter(IngestionJob.status.in_(["running", "queued"]))
            .distinct()
            .all()
        ]
        db.commit()

        totals = {
            "tenants": 0,
            "scanned": 0,
            "requeued": 0,
            "dispatched": 0,
            "dead_lettered": 0,
            "dispatch_failed": 0,
        }
        stale_before = datetime.now(timezone.utc) - timedelta(
            seconds=max(300, int(settings.INGESTION_STALE_AFTER_SECONDS))
        )
        for raw_tenant_id in tenant_ids:
            tenant_id = (
                raw_tenant_id
                if isinstance(raw_tenant_id, UUID)
                else UUID(str(raw_tenant_id))
            )
            apply_rls_context(db, tenant_id)
            result = reconcile_stale_ingestion_jobs(
                db,
                tenant_id=tenant_id,
                stale_before=stale_before,
                max_attempts=max(1, int(settings.INGESTION_MAX_ATTEMPTS)),
            )
            db.commit()
            totals["tenants"] += 1
            for key in ("scanned", "requeued", "dead_lettered"):
                totals[key] += int(result[key])

            recovery_ids = set(result["requeued_job_ids"])
            recovery_ids.update(
                str(row[0])
                for row in db.query(IngestionJob.id).filter(
                    IngestionJob.tenant_id == tenant_id,
                    IngestionJob.status == "queued",
                    IngestionJob.phase == "reconciled_retry",
                )
            )
            for job_id in recovery_ids:
                job = db.query(IngestionJob).filter(
                    IngestionJob.tenant_id == tenant_id,
                    IngestionJob.id == UUID(job_id),
                    IngestionJob.status == "queued",
                ).first()
                if job is None:
                    continue
                try:
                    get_ingestion_orchestrator().transition(
                        db,
                        job,
                        to_status="running",
                        phase="recovery_dispatching",
                        details={"reason": "stale_worker_recovery"},
                    )
                    db.commit()
                    # Persist running before publishing to the broker. A fast
                    # worker can otherwise finish while this task overwrites
                    # its terminal state back to running.
                    dispatch_ingestion_job(db, job)
                    db.rollback()
                    totals["dispatched"] += 1
                except Exception:
                    db.rollback()
                    totals["dispatch_failed"] += 1
                    failed_dispatch = db.query(IngestionJob).filter(
                        IngestionJob.tenant_id == tenant_id,
                        IngestionJob.id == UUID(job_id),
                        IngestionJob.status == "running",
                        IngestionJob.phase == "recovery_dispatching",
                    ).first()
                    if failed_dispatch is not None:
                        get_ingestion_orchestrator().transition(
                            db,
                            failed_dispatch,
                            to_status="queued",
                            phase="reconciled_retry",
                            error={
                                "code": "broker_dispatch_failed",
                                "category": "transient",
                                "retryable": True,
                                "user_message": "背景工作排程暫時失敗，系統將自動再次嘗試。",
                            },
                        )
                        db.commit()
                    logger.exception("stale ingestion dispatch failed: job=%s", job_id)
        return totals
    finally:
        db.close()
