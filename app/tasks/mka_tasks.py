"""MKA 背景任務：retention purge（§12.1）與非同步表單匯出（§13.2 queue delay）。

每日由 Celery beat 觸發 purge；匯出由 API 排程，渲染後存入 StorageBackend。
"""
from __future__ import annotations

import logging
import os
import tempfile
import uuid as _uuid
from uuid import UUID

from app.celery_app import celery_app
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


@celery_app.task(name="tasks.purge_mka_retention", bind=True, max_retries=2)
def purge_mka_retention(self):
    """硬刪過期語音轉寫 session；回傳刪除統計供 audit。"""
    db = SessionLocal()
    try:
        from app.services.rls import apply_rls_bypass

        apply_rls_bypass(db)
        from app.services.audio_retention import purge_expired_transcripts

        result = purge_expired_transcripts(db)
        db.commit()
        logger.info("purge_mka_retention done: %s", result)
        return result
    except Exception as exc:
        db.rollback()
        logger.exception("purge_mka_retention failed")
        raise self.retry(exc=exc, countdown=300)
    finally:
        db.close()


@celery_app.task(name="tasks.render_form_export", bind=True, max_retries=2)
def render_form_export(
    self,
    tenant_id: str,
    instance_id: str,
    actor_id: str,
    format: str,
    export_task_id: str | None = None,
):
    """非同步渲染已核准表單並存入 StorageBackend。

    actor 授權與 approved 狀態已在 API 排程前預檢；task 內以系統身分渲染，
    渲染結果仍取自 immutable snapshot（export_form 保證）。
    """
    job_id = export_task_id or getattr(getattr(self, "request", None), "id", None)
    if not job_id:
        job_id = str(_uuid.uuid4())
    db = SessionLocal()
    try:
        from app.services.rls import apply_rls_context

        apply_rls_context(db, UUID(tenant_id))

        from app.services.mka_persistence import MKARepository
        from app.services.storage import build_storage_key, get_storage_backend

        repo = MKARepository(db)
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

        key = build_storage_key(UUID(tenant_id), _uuid.uuid4(), result.format)
        fd, tmp_path = tempfile.mkstemp(suffix=f".{result.format}")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(result.content)
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
        # 必須 deepcopy：原地改共享 dict 會讓 SQLAlchemy 比對新舊值相等（history 為
        # unchanged），commit 時不產生 UPDATE，storage_key 靜默遺失
        import copy

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
        return {"storage_key": key, "filename": result.filename, "format": result.format}
    except Exception as exc:
        db.rollback()
        logger.exception("render_form_export failed")
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()
