"""Canonical dispatch for queued canonical-asset ingestion jobs."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.asset import AssetRevision, SourceAsset
from app.models.document import Document
from app.models.ingestion import IngestionJob


def dispatch_ingestion_job(db: Session, job: IngestionJob) -> str:
    """Dispatch one persisted job and return the Celery task identifier.

    The caller owns the transaction.  Dispatch is intentionally separate from
    state mutation so retry endpoints and stale-job reconciliation use exactly
    the same adapter routing.
    """

    revision = db.query(AssetRevision).filter(
        AssetRevision.tenant_id == job.tenant_id,
        AssetRevision.id == job.asset_revision_id,
    ).one()
    asset = db.query(SourceAsset).filter(
        SourceAsset.tenant_id == job.tenant_id,
        SourceAsset.id == revision.asset_id,
        SourceAsset.tombstoned_at.is_(None),
    ).one()

    if job.adapter_key == "core.video":
        from app.tasks.video_tasks import process_video_asset

        result = process_video_asset.delay(
            str(asset.tenant_id), str(revision.id), str(job.id)
        )
        return str(result.id)
    if job.adapter_key == "core.long_interview_audio":
        from app.tasks.audio_tasks import process_audio_asset

        result = process_audio_asset.delay(
            str(asset.tenant_id), str(revision.id), str(job.id)
        )
        return str(result.id)
    if job.adapter_key == "core.document":
        from app.tasks.document_tasks import process_document_task, process_url_task

        document = db.query(Document).filter(
            Document.tenant_id == asset.tenant_id,
            Document.source_asset_id == asset.id,
            Document.tombstoned_at.is_(None),
        ).first()
        if document is None:
            raise RuntimeError("document compatibility projection is unavailable")
        if document.source_type == "web":
            result = process_url_task.delay(
                str(document.id), str(document.file_path), str(asset.tenant_id)
            )
        else:
            result = process_document_task.delay(
                document_id=str(document.id),
                file_path=str(document.file_path),
                tenant_id=str(asset.tenant_id),
            )
        return str(result.id)
    raise RuntimeError(f"no dispatcher for adapter {job.adapter_key}")
