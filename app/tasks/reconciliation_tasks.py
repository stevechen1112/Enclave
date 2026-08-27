"""Celery tasks for projection reconciliation."""

from app.celery_app import celery_app
from app.db.session import MaintenanceSessionLocal
from app.models.outbox import ProjectionStatus
from app.services.reconciliation import reconcile_diverged_projections


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
