"""Persistent batch manifests for folder and connector ingestion."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.connector import ImportBatch, ImportBatchItem


class ConnectorBatchService:
    def create(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        connector_instance_id: UUID | None,
        resources: list[dict[str, Any]],
        shared_metadata: dict[str, Any] | None = None,
        created_by: UUID | None = None,
    ) -> ImportBatch:
        batch = ImportBatch(
            tenant_id=tenant_id,
            connector_instance_id=connector_instance_id,
            status="running",
            shared_metadata=dict(shared_metadata or {}),
            total_items=len(resources),
            created_by=created_by,
        )
        db.add(batch)
        db.flush()
        for resource in resources:
            record_id = str(resource.get("source_record_id") or "").strip()
            if not record_id:
                continue
            db.add(
                ImportBatchItem(
                    tenant_id=tenant_id,
                    batch_id=batch.id,
                    source_record_id=record_id,
                    parent_source_id=resource.get("parent_source_id"),
                    content_hash=resource.get("content_hash"),
                    resource_json=dict(resource),
                )
            )
        db.flush()
        return batch

    def mark(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        batch_id: UUID,
        source_record_id: str,
        succeeded: bool,
        asset_id: UUID | None = None,
        revision_id: UUID | None = None,
        error_code: str | None = None,
        error_detail: str | None = None,
    ) -> None:
        item = (
            db.query(ImportBatchItem)
            .filter(
                ImportBatchItem.tenant_id == tenant_id,
                ImportBatchItem.batch_id == batch_id,
                ImportBatchItem.source_record_id == source_record_id,
            )
            .first()
        )
        if item is None:
            return
        item.attempts += 1
        item.status = "succeeded" if succeeded else "failed"
        item.asset_id = asset_id
        item.revision_id = revision_id
        item.error_code = error_code
        item.error_detail = (error_detail or "")[:1000] or None
        self.recount(db, tenant_id=tenant_id, batch_id=batch_id)

    def recount(self, db: Session, *, tenant_id: UUID, batch_id: UUID) -> None:
        batch = (
            db.query(ImportBatch)
            .filter(ImportBatch.tenant_id == tenant_id, ImportBatch.id == batch_id)
            .first()
        )
        if batch is None:
            return
        rows = (
            db.query(ImportBatchItem)
            .filter(
                ImportBatchItem.tenant_id == tenant_id,
                ImportBatchItem.batch_id == batch_id,
            )
            .all()
        )
        batch.total_items = len(rows)
        batch.succeeded_items = sum(row.status == "succeeded" for row in rows)
        batch.failed_items = sum(row.status == "failed" for row in rows)
        unfinished = any(row.status in {"pending", "running"} for row in rows)
        if unfinished:
            batch.status = "running"
            batch.completed_at = None
        elif batch.failed_items and batch.succeeded_items:
            batch.status = "partial"
            batch.completed_at = datetime.now(timezone.utc)
        elif batch.failed_items:
            batch.status = "failed"
            batch.completed_at = datetime.now(timezone.utc)
        else:
            batch.status = "completed"
            batch.completed_at = datetime.now(timezone.utc)
        db.flush()

    def failed_resources(
        self, db: Session, *, tenant_id: UUID, batch_id: UUID
    ) -> list[dict[str, Any]]:
        return [
            dict(row.resource_json or {})
            for row in db.query(ImportBatchItem)
            .filter(
                ImportBatchItem.tenant_id == tenant_id,
                ImportBatchItem.batch_id == batch_id,
                ImportBatchItem.status == "failed",
            )
            .all()
        ]
