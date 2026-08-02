"""Celery tasks for projection reconciliation."""
from app.celery_app import celery_app
from app.db.session import SessionLocal
from app.services.reconciliation import reconcile_diverged_projections


@celery_app.task(name="tasks.reconcile_projections")
def reconcile_projections_batch():
    db = SessionLocal()
    try:
        return reconcile_diverged_projections(db)
    finally:
        db.close()
