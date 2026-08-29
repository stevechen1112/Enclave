"""Phase 3 — Connector lifecycle management."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.connector import ConnectorInstance, ConnectorResource
from app.services.outbox_events import publish_event

logger = logging.getLogger(__name__)

GA_CONNECTORS = [
    "nas_smb", "sharepoint", "google_drive", "confluence", "jira",
    "s3_minio", "github", "slack",
]


class ConnectorManager:
    def create_connector(
        self,
        db: Session,
        tenant_id: UUID,
        connector_type: str,
        name: str,
        config: Optional[Dict[str, Any]] = None,
    ) -> ConnectorInstance:
        from app.services.connector_schemas import validate_connector_config
        try:
            normalized = validate_connector_config(connector_type, config)
        except ValueError as exc:
            raise ValueError(f"invalid connector config: {exc}") from exc
        row = ConnectorInstance(
            tenant_id=tenant_id,
            connector_type=connector_type,
            name=name,
            config_json=normalized,
            status="active",
        )
        db.add(row)
        db.flush()
        publish_event(
            db,
            aggregate_type="connector",
            aggregate_id=str(row.id),
            event_type="created",
            revision=1,
            payload={"connector_type": connector_type, "tenant_id": str(tenant_id)},
        )
        db.commit()
        db.refresh(row)
        return row

    def pause(self, db: Session, connector_id: UUID) -> Optional[ConnectorInstance]:
        row = db.query(ConnectorInstance).filter(ConnectorInstance.id == connector_id).first()
        if not row:
            return None
        row.status = "paused"
        db.commit()
        db.refresh(row)
        return row

    def resume(self, db: Session, connector_id: UUID) -> Optional[ConnectorInstance]:
        row = db.query(ConnectorInstance).filter(ConnectorInstance.id == connector_id).first()
        if not row:
            return None
        row.status = "active"
        db.commit()
        db.refresh(row)
        return row

    def record_sync(
        self,
        db: Session,
        connector_id: UUID,
        resources: List[Dict[str, Any]],
    ) -> int:
        connector = db.query(ConnectorInstance).filter(ConnectorInstance.id == connector_id).first()
        if not connector:
            return 0
        count = 0
        for item in resources:
            existing = (
                db.query(ConnectorResource)
                .filter(
                    ConnectorResource.connector_instance_id == connector_id,
                    ConnectorResource.tenant_id == connector.tenant_id,
                    ConnectorResource.source_record_id == item["source_record_id"],
                )
                .first()
            )
            if existing:
                existing.source_version = item.get("source_version")
                existing.content_hash = item.get("content_hash")
                existing.acl_hash = item.get("acl_hash")
                existing.sync_state = "synced"
                existing.metadata_json = item.get("metadata", {})
            else:
                db.add(
                    ConnectorResource(
                        connector_instance_id=connector_id,
                        tenant_id=connector.tenant_id,
                        source_record_id=item["source_record_id"],
                        parent_source_id=item.get("parent_source_id"),
                        source_version=item.get("source_version"),
                        content_hash=item.get("content_hash"),
                        acl_hash=item.get("acl_hash"),
                        sync_state="synced",
                        metadata_json=item.get("metadata", {}),
                    )
                )
            count += 1
        connector.last_sync_at = datetime.now(timezone.utc)
        connector.last_error = None
        db.commit()
        return count

    def list_connectors(self, db: Session, tenant_id: UUID) -> List[ConnectorInstance]:
        return (
            db.query(ConnectorInstance)
            .filter(ConnectorInstance.tenant_id == tenant_id, ConnectorInstance.status != "deleted")
            .order_by(ConnectorInstance.created_at.desc())
            .all()
        )
