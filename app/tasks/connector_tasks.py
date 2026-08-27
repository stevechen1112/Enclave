"""Phase 3 — Celery tasks for connector sync + pending poll."""

from __future__ import annotations

import logging
from uuid import UUID

from app.celery_app import celery_app
from app.db.session import MaintenanceSessionLocal
from app.services.connector_sync import ConnectorSyncService

logger = logging.getLogger(__name__)
_sync_service = ConnectorSyncService()


@celery_app.task(name="tasks.sync_connector", bind=True, max_retries=2)
def sync_connector_task(self, connector_id: str, full_reindex: bool = False):
    from app.models.connector import ConnectorInstance
    from app.services.rls import apply_rls_bypass, apply_rls_context

    db = MaintenanceSessionLocal()
    try:
        apply_rls_bypass(
            db,
            actor_identity="celery:sync_connector",
            operation="resolve_connector_tenant",
            reason="Resolve tenant for legacy connector task payload",
            correlation_id=str(getattr(self.request, "id", "") or "") or None,
        )
        tenant_id = (
            db.query(ConnectorInstance.tenant_id)
            .filter(ConnectorInstance.id == UUID(connector_id))
            .scalar()
        )
        if tenant_id is None:
            raise LookupError("connector not found")
        apply_rls_context(db, tenant_id)
        result = _sync_service.run_sync(
            db, UUID(connector_id), full_reindex=full_reindex
        )
        return result
    except Exception as exc:
        logger.exception("sync_connector_task failed: %s", exc)
        raise
    finally:
        db.close()


@celery_app.task(name="tasks.poll_pending_connectors", bind=True, max_retries=0)
def poll_pending_connectors(self):
    """
    Resume connectors stuck in pipeshub_resync_pending by re-running sync
    (which polls records when PIPESHUB_POLL_AFTER_RESYNC=true).
    """
    from app.models.connector import ConnectorInstance

    from app.services.rls import apply_rls_bypass, apply_rls_context

    db = MaintenanceSessionLocal()
    try:
        apply_rls_bypass(
            db,
            actor_identity="celery:poll_pending_connectors",
            operation="list_pending_connectors",
            reason="Schedule tenant-scoped retries for pending connector syncs",
            correlation_id=str(getattr(self.request, "id", "") or "") or None,
        )
        rows = (
            db.query(ConnectorInstance)
            .filter(ConnectorInstance.status == "active")
            .all()
        )
        pending = [
            (r.id, r.tenant_id)
            for r in rows
            if (r.sync_state or {}).get("pending_remote")
            or str((r.sync_state or {}).get("mode", "")).endswith("_pending")
        ]
        db.commit()
        results = []
        for connector_id, tenant_id in pending[:20]:
            try:
                apply_rls_context(db, tenant_id)
                out = _sync_service.run_sync(db, connector_id, full_reindex=False)
                results.append(
                    {
                        "connector_id": str(connector_id),
                        "status": out.get("status"),
                        "mode": out.get("mode"),
                        "docs": len(out.get("document_ids") or []),
                    }
                )
            except Exception as exc:
                db.rollback()
                logger.warning(
                    "poll pending connector %s failed: %s", connector_id, exc
                )
                results.append(
                    {
                        "connector_id": str(connector_id),
                        "status": "error",
                        "error": str(exc)[:200],
                    }
                )
        return {"polled": len(results), "results": results}
    finally:
        db.close()
