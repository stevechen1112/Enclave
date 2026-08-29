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

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.connector import ConnectorInstance, ConnectorResource
from app.models.document import Document
from app.models.outbox import SyncCursor
from app.services.connector_manager import ConnectorManager
from app.services.external_principal import ExternalPrincipalService
from app.services.outbox_events import publish_event

logger = logging.getLogger(__name__)


def _hash_identity(value: Any) -> str:
    """Compare legacy bare SHA-256 and canonical ``sha256:`` values equally."""
    return str(value or "").strip().lower().removeprefix("sha256:")


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

    def _get_or_create_cursor(
        self, db: Session, connector: ConnectorInstance
    ) -> SyncCursor:
        cursor = (
            db.query(SyncCursor)
            .filter(
                SyncCursor.tenant_id == connector.tenant_id,
                SyncCursor.connector_instance_id == str(connector.id),
            )
            .first()
        )
        if cursor:
            return cursor
        cursor = SyncCursor(
            tenant_id=connector.tenant_id,
            connector_instance_id=str(connector.id),
            connector_type=connector.connector_type,
            sync_state={},
        )
        try:
            # The API request and outbox worker may both observe a missing
            # cursor immediately after connector creation. Keep a uniqueness
            # race inside a savepoint so the request transaction remains usable.
            with db.begin_nested():
                db.add(cursor)
                db.flush()
        except IntegrityError:
            cursor = (
                db.query(SyncCursor)
                .filter(
                    SyncCursor.tenant_id == connector.tenant_id,
                    SyncCursor.connector_instance_id == str(connector.id),
                )
                .first()
            )
            if cursor is None:
                raise
        return cursor

    @staticmethod
    def _flush_document_idempotently(db: Session, document: Document) -> Document:
        """Persist a materialized document or return a concurrent identical winner."""
        try:
            with db.begin_nested():
                db.add(document)
                db.flush()
            return document
        except IntegrityError:
            winner = (
                db.query(Document)
                .filter(
                    Document.tenant_id == document.tenant_id,
                    Document.source_system == document.source_system,
                    Document.source_record_id == document.source_record_id,
                    Document.tombstoned_at.is_(None),
                )
                .first()
            )
            if winner is None or _hash_identity(winner.content_hash) != _hash_identity(
                document.content_hash
            ):
                raise
            return winner

    async def _fetch_remote_sync(
        self,
        connector: ConnectorInstance,
        full_reindex: bool = False,
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
        if _mock_allowed(config) and (
            config.get("mock_resources") or config.get("mock_acl_entries")
        ):
            return {
                "status": "completed",
                "mode": "local_mock",
                "resources": config.get("mock_resources", []),
                "acl_entries": config.get("mock_acl_entries", []),
                "cursor": config.get("cursor", "simulated-cursor"),
                "snapshot_complete": bool(config.get("mock_snapshot_complete", False)),
                "delete_semantics": "tombstone",
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
        batch_id: Optional[UUID] = None,
    ) -> List[str]:
        """
        將 connector resources 寫入 Enclave canonical documents，並觸發解析索引。
        """
        from app.config import settings
        from app.services.asset_projection import project_document
        from app.services.connector_asset import materialize_connector_asset
        from app.services.connector_batch import ConnectorBatchService
        from app.tasks.document_tasks import process_document_task

        created_ids: List[str] = []
        upload_root = Path(settings.UPLOAD_DIR) / str(connector.tenant_id)
        upload_root.mkdir(parents=True, exist_ok=True)
        batch_service = ConnectorBatchService()

        for item in resources:
            src = item.get("file_path")
            if not src or not Path(src).is_file():
                # P3-1：雲端 resource 無本機 file_path，嘗試下載
                if settings.CONNECTOR_MATERIALIZE_ENABLED:
                    from app.services.connector_materialize import (
                        get_resource_downloader,
                    )

                    downloader = get_resource_downloader()
                    downloaded = downloader.resolve_and_download(
                        item, str(connector.tenant_id)
                    )
                    if downloaded:
                        src = downloaded
                        item["file_path"] = downloaded  # 更新 item 供後續使用
                    else:
                        if batch_id:
                            batch_service.mark(
                                db,
                                tenant_id=connector.tenant_id,
                                batch_id=batch_id,
                                source_record_id=str(item.get("source_record_id") or ""),
                                succeeded=False,
                                error_code="content_unavailable",
                            )
                        continue
                else:
                    if batch_id:
                        batch_service.mark(
                            db,
                            tenant_id=connector.tenant_id,
                            batch_id=batch_id,
                            source_record_id=str(item.get("source_record_id") or ""),
                            succeeded=False,
                            error_code="materialize_disabled",
                        )
                    continue
            src_path = Path(src)
            content_hash = (
                item.get("content_hash")
                or hashlib.sha256(src_path.read_bytes()).hexdigest()
            )

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
            if existing and _hash_identity(existing.content_hash) == _hash_identity(
                content_hash
            ):
                created_ids.append(str(existing.id))
                resource_row = (
                    db.query(ConnectorResource)
                    .filter(
                        ConnectorResource.tenant_id == connector.tenant_id,
                        ConnectorResource.connector_instance_id == connector.id,
                        ConnectorResource.source_record_id == item["source_record_id"],
                    )
                    .first()
                )
                if resource_row:
                    resource_row.document_id = existing.id
                if batch_id:
                    projection = project_document(db, existing)
                    batch_service.mark(
                        db,
                        tenant_id=connector.tenant_id,
                        batch_id=batch_id,
                        source_record_id=str(item["source_record_id"]),
                        succeeded=True,
                        asset_id=projection.asset.id,
                        revision_id=projection.revision.id if projection.revision else None,
                    )
                continue

            doc_id = existing.id if existing else uuid4()
            dest = upload_root / f"{doc_id}{src_path.suffix.lower() or '.bin'}"
            shutil.copy2(src_path, dest)

            # Canonical asset/revision is the primary persistence path. Document
            # remains a parser compatibility bridge and can be retired later.
            asset, revision = materialize_connector_asset(
                db,
                tenant_id=connector.tenant_id,
                source_system=connector.connector_type,
                resource={**item, "content_hash": content_hash},
                content_uri=str(dest),
                byte_size=dest.stat().st_size,
                created_by=uploaded_by,
            )

            if existing:
                existing.filename = item.get("title") or src_path.name
                existing.file_type = src_path.suffix.lstrip(".").lower() or "bin"
                existing.file_path = str(dest)
                existing.file_size = dest.stat().st_size
                existing.external_version = item.get("source_version")
                existing.content_hash = content_hash
                existing.version = revision.revision
                existing.status = "processing"
                existing.error_message = None
                existing.source_asset_id = asset.id
                doc = existing
            else:
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
                    version=revision.revision,
                    status="processing",
                    uploaded_by=uploaded_by,
                    source_asset_id=asset.id,
                )
            persisted = doc if existing else self._flush_document_idempotently(db, doc)
            if persisted is not doc:
                try:
                    dest.unlink(missing_ok=True)
                except OSError:
                    logger.warning("failed to clean duplicate connector copy %s", dest)
                created_ids.append(str(persisted.id))
                continue
            projection = project_document(
                db,
                doc,
                content_uri=str(dest),
                content_hash=content_hash,
                ingestion_status="pending",
            )
            created_ids.append(str(doc_id))
            resource_row = (
                db.query(ConnectorResource)
                .filter(
                    ConnectorResource.tenant_id == connector.tenant_id,
                    ConnectorResource.connector_instance_id == connector.id,
                    ConnectorResource.source_record_id == item["source_record_id"],
                )
                .first()
            )
            if resource_row:
                resource_row.document_id = doc.id
            if batch_id:
                batch_service.mark(
                    db,
                    tenant_id=connector.tenant_id,
                    batch_id=batch_id,
                    source_record_id=str(item["source_record_id"]),
                    succeeded=True,
                    asset_id=projection.asset.id,
                    revision_id=projection.revision.id if projection.revision else None,
                )

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

        if batch_id:
            batch_service.recount(
                db, tenant_id=connector.tenant_id, batch_id=batch_id
            )
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

        live_ids = {
            r["source_record_id"] for r in resources if r.get("source_record_id")
        }
        scoped_source_ids = {
            str(value)
            for (value,) in db.query(ConnectorResource.source_record_id)
            .filter(
                ConnectorResource.tenant_id == connector.tenant_id,
                ConnectorResource.connector_instance_id == connector.id,
            )
            .all()
        }
        document_query = db.query(Document).filter(
            Document.tenant_id == connector.tenant_id,
            Document.source_system == connector.connector_type,
            Document.tombstoned_at.is_(None),
        )
        # Pre-I6 direct service callers did not create ConnectorResource rows.
        # Keep that compatibility path; production run_sync always scopes by
        # connector resources before lifecycle reconciliation.
        if scoped_source_ids:
            document_query = document_query.filter(
                Document.source_record_id.in_(scoped_source_ids)
            )
        existing_docs = (
            document_query.all()
        )
        existing_source_ids = {
            str(doc.source_record_id) for doc in existing_docs if doc.source_record_id
        }
        new_records_by_hash: dict[str, list[str]] = {}
        for resource in resources:
            record_id = str(resource.get("source_record_id") or "")
            digest = _hash_identity(resource.get("content_hash"))
            if record_id and digest and record_id not in existing_source_ids:
                new_records_by_hash.setdefault(digest, []).append(record_id)
        tombstoned = 0
        renamed = 0
        for doc in existing_docs:
            if not doc.source_record_id:
                continue
            if doc.source_record_id in live_ids:
                continue
            # Rename only when the content hash identifies one unambiguous new
            # source. Duplicate-content folders must never collapse identities.
            candidates = new_records_by_hash.get(_hash_identity(doc.content_hash), [])
            if len(candidates) == 1:
                new_id = candidates.pop()
                doc.source_record_id = new_id
                doc.external_version = (
                    str(int(doc.external_version or 0) + 1)
                    if str(doc.external_version or "").isdigit()
                    else "renamed"
                )
                renamed += 1
                continue
            if crud_document.tombstone(
                db, document_id=doc.id, reason="connector_deleted"
            ):
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
        connector = (
            db.query(ConnectorInstance)
            .filter(ConnectorInstance.id == connector_id)
            .with_for_update()
            .first()
        )
        if not connector:
            return {"status": "error", "error": "connector_not_found"}
        if connector.status == "paused":
            return {"status": "skipped", "reason": "connector_paused"}

        cursor_row = self._get_or_create_cursor(db, connector)
        try:
            result = asyncio.run(
                self._fetch_remote_sync(connector, full_reindex=full_reindex)
            )
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
        acl_result = {"applied": 0, "revoked": 0}
        snapshot_complete = bool(result.get("snapshot_complete", False))
        live_source_ids = {
            str(item["source_record_id"])
            for item in resources
            if item.get("source_record_id")
        }
        if snapshot_complete:
            acl_result = self._principal_service.replace_acl_snapshot(
                db,
                connector.tenant_id,
                acl_entries,
                source_record_ids=live_source_ids,
            )
        elif acl_entries:
            acl_result["applied"] = self._principal_service.apply_acl_entries(
                db, connector.tenant_id, acl_entries
            )

        count = self._manager.record_sync(db, connector_id, resources)

        lifecycle = {"tombstoned": 0, "renamed": 0}
        # Delete/rename reconciliation is allowed only for an explicitly complete
        # snapshot. Empty complete snapshots are meaningful; partial pages are not.
        if (
            materialize
            and snapshot_complete
            and result.get("delete_semantics", "tombstone") == "tombstone"
        ):
            lifecycle = self.reconcile_deletes_and_renames(db, connector, resources)

        doc_ids: List[str] = []
        batch_id: UUID | None = None
        if materialize and resources:
            from app.services.connector_batch import ConnectorBatchService

            batch = ConnectorBatchService().create(
                db,
                tenant_id=connector.tenant_id,
                connector_instance_id=connector.id,
                resources=resources,
                shared_metadata={
                    "connector_type": connector.connector_type,
                    "snapshot_id": result.get("snapshot_id"),
                    "snapshot_complete": snapshot_complete,
                },
                created_by=uploaded_by,
            )
            batch_id = batch.id
            doc_ids = self.materialize_to_documents(
                db,
                connector,
                resources,
                uploaded_by=uploaded_by,
                batch_id=batch_id,
            )

        new_cursor = result.get("cursor")
        if new_cursor:
            cursor_row.cursor = new_cursor
            connector.sync_state = {
                **(connector.sync_state or {}),
                "cursor": new_cursor,
                "mode": mode,
                "pending_remote": False,
                "snapshot_complete": snapshot_complete,
                "snapshot_id": result.get("snapshot_id"),
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
            revision=int(cursor_row.watermark.timestamp())
            if cursor_row.watermark
            else 1,
            payload={
                "tenant_id": str(connector.tenant_id),
                "resource_count": count,
                "document_ids": doc_ids,
                "batch_id": str(batch_id) if batch_id else None,
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
            "acl_applied": acl_result["applied"],
            "acl_revoked": acl_result["revoked"],
            "snapshot_complete": snapshot_complete,
            "mode": mode,
            "document_ids": doc_ids,
            "batch_id": str(batch_id) if batch_id else None,
            "lifecycle": lifecycle,
        }

    def rotate_credential_ref(
        self,
        db: Session,
        connector_id: UUID,
        credential_ref: str,
    ) -> Optional[ConnectorInstance]:
        row = (
            db.query(ConnectorInstance)
            .filter(ConnectorInstance.id == connector_id)
            .first()
        )
        if not row:
            return None
        row.credential_ref = credential_ref
        publish_event(
            db,
            aggregate_type="connector",
            aggregate_id=str(connector_id),
            event_type="credential_rotated",
            revision=1,
            payload={
                "tenant_id": str(row.tenant_id),
                "credential_ref": credential_ref,
            },
        )
        db.commit()
        db.refresh(row)
        return row

    def delete_connector(self, db: Session, connector_id: UUID) -> bool:
        row = (
            db.query(ConnectorInstance)
            .filter(ConnectorInstance.id == connector_id)
            .first()
        )
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
        self,
        db: Session,
        tenant_id: UUID,
        source_record_id: str,
        limit: int = 20,
    ) -> List[dict]:
        return self._principal_service.sample_acl_for_source(
            db,
            tenant_id,
            source_record_id,
            limit=limit,
        )
