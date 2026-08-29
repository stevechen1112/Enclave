"""Maintenance tasks for platform Input transport state."""
from __future__ import annotations

import logging

from app.celery_app import celery_app
from app.db.session import MaintenanceSessionLocal

logger = logging.getLogger(__name__)


@celery_app.task(name="tasks.expire_upload_sessions", bind=True, max_retries=2)
def expire_upload_sessions(self):
    db = MaintenanceSessionLocal()
    try:
        from app.services.rls import apply_rls_bypass

        apply_rls_bypass(
            db,
            actor_identity="celery:expire_upload_sessions",
            operation="expire_upload_sessions",
            reason="Remove expired cross-tenant resumable transport spools",
            correlation_id=str(getattr(self.request, "id", "") or "") or None,
        )
        from app.services.resumable_upload import expire_sessions

        count = expire_sessions(db)
        db.commit()
        return {"expired_sessions": count}
    except Exception as exc:
        db.rollback()
        logger.exception("expire_upload_sessions failed")
        raise self.retry(exc=exc, countdown=300)
    finally:
        db.close()
