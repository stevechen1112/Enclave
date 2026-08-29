"""Core Workflow background tasks."""

from __future__ import annotations

import copy
import logging
import os
import tempfile
import uuid
from uuid import UUID

from app.celery_app import celery_app
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


@celery_app.task(name="tasks.render_form_export", bind=True, max_retries=2)
def render_form_export(
    self,
    tenant_id: str,
    instance_id: str,
    actor_id: str,
    format: str,
    export_task_id: str | None = None,
):
    """Render an approved immutable form snapshot into tenant storage."""
    job_id = export_task_id or getattr(getattr(self, "request", None), "id", None)
    if not job_id:
        job_id = str(uuid.uuid4())
    db = SessionLocal()
    try:
        from app.services.rls import apply_rls_context
        from app.services.storage import build_storage_key, get_storage_backend
        from app.services.workflow_repository import WorkflowRepository

        apply_rls_context(db, UUID(tenant_id))
        repo = WorkflowRepository(db)
        result = repo.export_form(
            tenant_id=UUID(tenant_id),
            instance_id=UUID(instance_id),
            actor_id=UUID(actor_id),
            is_superuser=True,
            format=format,
            artifact_extra={"task_id": job_id, "status": "processing"},
        )
        if not result.success:
            raise RuntimeError(result.error or "export render failed")

        key = build_storage_key(UUID(tenant_id), uuid.uuid4(), result.format)
        fd, tmp_path = tempfile.mkstemp(suffix=f".{result.format}")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(result.content)
            get_storage_backend().put(key, tmp_path)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

        row = repo.assert_form_exportable(
            tenant_id=UUID(tenant_id),
            instance_id=UUID(instance_id),
            actor_id=UUID(actor_id),
            is_superuser=True,
        )
        artifacts = copy.deepcopy(list(row.export_artifacts or []))
        matched = False
        for item in reversed(artifacts):
            if item.get("task_id") == job_id:
                item["storage_key"] = key
                item["status"] = "completed"
                matched = True
                break
        if not matched:
            raise RuntimeError(f"export artifact not found for task_id={job_id}")
        row.export_artifacts = artifacts
        db.commit()
        logger.info("render_form_export done: %s", key)
        return {
            "storage_key": key,
            "filename": result.filename,
            "format": result.format,
        }
    except Exception as exc:
        db.rollback()
        logger.exception("render_form_export failed")
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()
