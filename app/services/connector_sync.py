"""Phase 3 — Connector sync orchestration (NAS local + PipesHub + ACL)."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.models.connector import ConnectorInstance
from app.models.document import Document
from app.models.outbox import SyncCursor
from app.services.connector_manager import ConnectorManager
from app.services.external_principal import ExternalPrincipalService
from app.services.outbox_events import publish_event

logger = logging.getLogger(__name__)


def _mock_allowed(config: Dict[str, Any]) -> bool:
    """生產環境禁止 mock；開發需明確 allow_mock / PIPESHUB_ALLOW_MOCK。"""
    from app.config import settings
    if settings.is_production:
        return False
    if str(config.get("allow_mock", "")).lower() == "true":
        return True
    return os.getenv("PIPESHUB_ALLOW_MOCK", "false").lower() == "true"


class ConnectorSyncService:
    def __init__(self):
        self._manager = ConnectorManager()
        self._principal_service = ExternalPrincipalService()

    def _get_or_create_cursor(self, db: Session, connector: ConnectorInstance) -> SyncCursor:
        cursor = (
            db.query(SyncCursor)
            .filter(SyncCursor.connector_instance_id == str(connector.id))
            .first()
        )
        if cursor:
            return cursor
        cursor = SyncCursor(
            connector_instance_id=str(connector.id),
            connector_type=connector.connector_type,
            sync_state={},
        )
        db.add(cursor)
        db.flush()
        return cursor

    async def _fetch_remote_sync(
        self, connector: ConnectorInstance, full_reindex: bool = False,
    ) -> Dict[str, Any]:
        config = dict(connector.config_json or {})
        config["connector_instance_id"] = str(connector.id)
        config["cursor"] = connector.sync_state.get("cursor")
        config["full_reindex"] = full_reindex

        # 1) 真實本機 NAS/目錄掃描（第一批 GA：nas_smb）
        root_path = config.get("root_path") or config.get("share_path")
        if connector.connector_type in ("nas_smb", "local_fs") and root_path:
            from app.services.nas_local_connector import scan_local_nas
            return scan_local_nas(
                str(root_path),
                max_files=int(config.get("max_files", 200)),
                principal_external_id=str(
                    config.get("principal_external_id", "nas-local-reader")
                ),
            )

        # 2) PipesHub sidecar
        if os.getenv("PIPESHUB_ENABLED", "").lower() == "true":
            from app.gateway.adapters.pipeshub_http import PipesHubHTTPAdapter
            from app.gateway.token_provider import build_pipeshub_token_provider
            adapter = PipesHubHTTPAdapter(
                base_url=os.getenv("PIPESHUB_BASE_URL", "http://pipeshub-api:3000"),
                api_key=os.getenv("PIPESHUB_API_KEY", ""),
                token_provider=build_pipeshub_token_provider(),
            )
            return await adapter.sync_connector(connector.connector_type, config)

        # 3) 明確 mock（僅非生產）
        if _mock_allowed(config) and (config.get("mock_resources") or config.get("mock_acl_entries")):
            return {
                "status": "completed",
                "mode": "local_mock",
                "resources": config.get("mock_resources", []),
                "acl_entries": config.get("mock_acl_entries", []),
                "cursor": config.get("cursor", "simulated-cursor"),
            }
        return {
            "status": "error",
            "error": "no_real_connector_source_configured",
        }

    def materialize_to_documents(
        self,
        db: Session,
        connector: ConnectorInstance,
        resources: List[Dict[str, Any]],
        uploaded_by: Optional[UUID] = None,
    ) -> List[str]:
        """
        將 connector resources 寫入 Enclave canonical documents，並觸發解析索引。
        """
        from app.config import settings
        from app.tasks.document_tasks import process_document_task

        created_ids: List[str] = []
        upload_root = Path(settings.UPLOAD_DIR) / str(connector.tenant_id)
        upload_root.mkdir(parents=True, exist_ok=True)

        for item in resources:
            src = item.get("file_path")
            if not src or not Path(src).is_file():
                # P3-1：雲端 resource 無本機 file_path，嘗試下載
                if settings.CONNECTOR_MATERIALIZE_ENABLED:
                    from app.services.connector_materialize import get_resource_downloader
                    downloader = get_resource_downloader()
                    downloaded = downloader.resolve_and_download(item, str(connector.tenant_id))
                    if downloaded:
                        src = downloaded
                        item["file_path"] = downloaded  # 更新 item 供後續使用
                    else:
                        continue
                else:
                    continue
            src_path = Path(src)
            content_hash = item.get("content_hash") or hashlib.sha256(src_path.read_bytes()).hexdigest()

            existing = (
                db.query(Document)
                .filter(
                    Document.tenant_id == connector.tenant_id,
                    Document.source_system == connector.connector_type,
                    Document.source_record_id == item["source_record_id"],
                    Document.tombstoned_at.is_(None),
                )
                .first()
            )
            if existing and existing.content_hash == content_hash:
                created_ids.append(str(existing.id))
                continue

            doc_id = uuid4()
            dest = upload_root / f"{doc_id}{src_path.suffix.lower() or '.bin'}"
            shutil.copy2(src_path, dest)

            doc = Document(
                id=doc_id,
                tenant_id=connector.tenant_id,
                filename=item.get("title") or src_path.name,
                file_type=src_path.suffix.lstrip(".").lower() or "bin",
                file_path=str(dest),
                file_size=dest.stat().st_size,
                source_type="connector",
                source_system=connector.connector_type,
                source_record_id=item["source_record_id"],
                external_version=item.get("source_version"),
                content_hash=content_hash,
                status="processing",
                uploaded_by=uploaded_by,
            )
            db.add(doc)
            db.flush()
            created_ids.append(str(doc_id))

            try:
                process_document_task.delay(
                    document_id=str(doc_id),
                    file_path=str(dest),
                    tenant_id=str(connector.tenant_id),
                )
            except Exception:
                try:
                    process_document_task.run(
                        document_id=str(doc_id),
                        file_path=str(dest),
                        tenant_id=str(connector.tenant_id),
                    )
                except Exception as exc:
                    logger.error("materialize process failed %s: %s", doc_id, exc)
                    doc.status = "failed"
                    doc.error_message = str(exc)[:500]

        db.commit()
        return created_ids

    def reconcile_deletes_and_renames(
        self,
        db: Session,
        connector: ConnectorInstance,
        resources: List[Dict[str, Any]],
    ) -> Dict[str, int]:
        """
        Sync lifecycle:
        - source_record_id 消失 → tombstone
        - 同 content_hash 但 source_record_id 變更 → 視為 rename（更新 record id，不重建）
        """
        from app.crud import crud_document

        live_ids = {r["source_record_id"] for r in resources if r.get("source_record_id")}
        hash_to_record = {
            r["content_hash"]: r["source_record_id"]
            for r in resources
            if r.get("content_hash") and r.get("source_record_id")
        }
        existing_docs = (
            db.query(Document)
            .filter(
                Document.tenant_id == connector.tenant_id,
                Document.source_system == connector.connector_type,
                Document.tombstoned_at.is_(None),
            )
            .all()
        )
        tombstoned = 0
        renamed = 0
        for doc in existing_docs:
            if not doc.source_record_id:
                continue
            if doc.source_record_id in live_ids:
                continue
            # rename: same hash appears under new record id
            new_id = hash_to_record.get(doc.content_hash or "")
            if new_id and new_id != doc.source_record_id:
                doc.source_record_id = new_id
                doc.external_version = str(int(doc.external_version or 0) + 1) if str(doc.external_version or "").isdigit() else "renamed"
                renamed += 1
                continue
            if crud_document.tombstone(db, document_id=doc.id, reason="connector_deleted"):
                tombstoned += 1
        if tombstoned or renamed:
            db.commit()
        return {"tombstoned": tombstoned, "renamed": renamed}

    def run_sync(
        self,
        db: Session,
        connector_id: UUID,
        full_reindex: bool = False,
        materialize: bool = True,
        uploaded_by: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        connector = db.query(ConnectorInstance).filter(ConnectorInstance.id == connector_id).first()
        if not connector:
            return {"status": "error", "error": "connector_not_found"}
        if connector.status == "paused":
            return {"status": "skipped", "reason": "connector_paused"}

        cursor_row = self._get_or_create_cursor(db, connector)
        try:
            result = asyncio.run(self._fetch_remote_sync(connector, full_reindex=full_reindex))
        except Exception as exc:
            connector.last_error = str(exc)[:500]
            db.commit()
            logger.error("Connector sync failed %s: %s", connector_id, exc)
            return {"status": "error", "error": str(exc)}

        if result.get("status") == "error":
            connector.last_error = result.get("error", "sync_failed")[:500]
            db.commit()
            return result

        resources = result.get("resources", [])
        acl_entries = result.get("acl_entries", [])
        mode = str(result.get("mode") or "")
        # 非同步 resync（空資源）禁止跑 delete reconcile，否則會誤刪全部文件
        async_pending = (
            result.get("status") == "submitted"
            or mode.endswith("_pending")
            or (mode.startswith("pipeshub_resync") and not resources)
        )

        if async_pending:
            connector.sync_state = {
                **(connector.sync_state or {}),
                "cursor": result.get("cursor"),
                "mode": mode or "pipeshub_resync_pending",
                "pending_remote": True,
            }
            connector.last_error = None
            publish_event(
                db,
                aggregate_type="connector",
                aggregate_id=str(connector_id),
                event_type="sync_submitted",
                revision=int(datetime.now(timezone.utc).timestamp()),
                payload={
                    "tenant_id": str(connector.tenant_id),
                    "mode": mode,
                    "pipeshub_connector_id": result.get("pipeshub_connector_id"),
                    "full_reindex": full_reindex,
                },
            )
            db.commit()
            return {
                "status": "submitted",
                "connector_id": str(connector_id),
                "synced_resources": 0,
                "acl_entries": 0,
                "mode": mode or "pipeshub_resync_pending",
                "document_ids": [],
                "lifecycle": {"tombstoned": 0, "renamed": 0, "pending_remote": True},
                "note": result.get("note") or "awaiting remote resource projection",
            }

        # 將 NAS/connector principal 映射到觸發 sync 的使用者（fail-closed 前提）
        if acl_entries and uploaded_by:
            mapped_entries = []
            for entry in acl_entries:
                e = dict(entry)
                e.setdefault("mapped_subject_id", uploaded_by)
                e.setdefault("mapped_subject_type", "user")
                mapped_entries.append(e)
            acl_entries = mapped_entries
            self._principal_service.apply_acl_entries(db, connector.tenant_id, acl_entries)
        elif acl_entries:
            self._principal_service.apply_acl_entries(db, connector.tenant_id, acl_entries)

        count = self._manager.record_sync(db, connector_id, resources)

        lifecycle = {"tombstoned": 0, "renamed": 0}
        # 僅在拿到完整資源清單時才 reconcile deletes（空清單 = 未知，不可刪）
        if materialize and resources:
            lifecycle = self.reconcile_deletes_and_renames(db, connector, resources)

        doc_ids: List[str] = []
        if materialize and resources:
            doc_ids = self.materialize_to_documents(
                db, connector, resources, uploaded_by=uploaded_by,
            )

        new_cursor = result.get("cursor")
        if new_cursor:
            cursor_row.cursor = new_cursor
            connector.sync_state = {
                **(connector.sync_state or {}),
                "cursor": new_cursor,
                "mode": mode,
                "pending_remote": False,
            }
        cursor_row.last_success_at = datetime.now(timezone.utc)
        cursor_row.watermark = datetime.now(timezone.utc)
        cursor_row.sync_state = result.get("sync_state", {})
        connector.last_error = None

        publish_event(
            db,
            aggregate_type="connector",
            aggregate_id=str(connector_id),
            event_type="sync_completed",
            revision=int(cursor_row.watermark.timestamp()) if cursor_row.watermark else 1,
            payload={
                "tenant_id": str(connector.tenant_id),
                "resource_count": count,
                "document_ids": doc_ids,
                "mode": mode,
                "full_reindex": full_reindex,
            },
        )
        db.commit()
        return {
            "status": "completed",
            "connector_id": str(connector_id),
            "synced_resources": count,
            "acl_entries": len(acl_entries),
            "mode": mode,
            "document_ids": doc_ids,
            "lifecycle": lifecycle,
        }

    def rotate_credential_ref(
        self, db: Session, connector_id: UUID, credential_ref: str,
    ) -> Optional[ConnectorInstance]:
        row = db.query(ConnectorInstance).filter(ConnectorInstance.id == connector_id).first()
        if not row:
            return None
        row.credential_ref = credential_ref
        publish_event(
            db,
            aggregate_type="connector",
            aggregate_id=str(connector_id),
            event_type="credential_rotated",
            revision=1,
            payload={"credential_ref": credential_ref},
        )
        db.commit()
        db.refresh(row)
        return row

    def delete_connector(self, db: Session, connector_id: UUID) -> bool:
        row = db.query(ConnectorInstance).filter(ConnectorInstance.id == connector_id).first()
        if not row:
            return False
        row.status = "deleted"
        publish_event(
            db,
            aggregate_type="connector",
            aggregate_id=str(connector_id),
            event_type="deleted",
            revision=1,
            payload={"tenant_id": str(row.tenant_id)},
        )
        db.commit()
        return True

    def sample_acl(
        self, db: Session, tenant_id: UUID, source_record_id: str, limit: int = 20,
    ) -> List[dict]:
        return self._principal_service.sample_acl_for_source(
            db, tenant_id, source_record_id, limit=limit,
        )
