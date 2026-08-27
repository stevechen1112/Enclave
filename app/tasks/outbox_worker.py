"""
Phase 0 — Outbox Worker (Celery Task)

從 outbox_events 表中讀取待處理事件，分派到對應的 Adapter。
實作 at-least-once delivery + 冪等性 + dead-letter。
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.core.authorization import AuthorizationContext
from app.db.session import MaintenanceSessionLocal
from app.gateway.adapter_factory import PROJECTION_PROVIDERS, build_projection_adapters
from app.gateway.resource_registry import ResourceRegistry
from app.models.outbox import DeadLetterEvent, OutboxEvent, ProjectionStatus

logger = logging.getLogger(__name__)

MAX_RETRIES = 5
RETRY_BACKOFF_SECONDS = [10, 30, 60, 300, 900]
POLL_BATCH_SIZE = 50
POLL_INTERVAL_SECONDS = 5

_registry = ResourceRegistry()
_projection_adapters: Optional[Dict[str, Any]] = None


def _get_projection_adapters() -> Dict[str, Any]:
    global _projection_adapters
    if _projection_adapters is None:
        _projection_adapters = build_projection_adapters()
    return _projection_adapters


def _authz_from_payload(payload: Dict[str, Any]) -> AuthorizationContext:
    tenant_id = UUID(payload.get("tenant_id", "00000000-0000-0000-0000-000000000000"))
    subject_id = UUID(
        payload.get(
            "uploaded_by",
            payload.get("subject_id", "00000000-0000-0000-0000-000000000001"),
        )
    )
    return AuthorizationContext(
        tenant_id=tenant_id,
        subject_id=subject_id,
        role_ids=["admin"],
        is_superuser=True,
        policy_revision=1,
    )


def _upsert_projection_status(
    db: Session,
    tenant_id: UUID,
    resource_type: str,
    resource_id: str,
    provider: str,
    desired_revision: int,
    applied_revision: int,
    state: str,
    error: Optional[str] = None,
) -> ProjectionStatus:
    row = (
        db.query(ProjectionStatus)
        .filter(
            ProjectionStatus.tenant_id == tenant_id,
            ProjectionStatus.resource_type == resource_type,
            ProjectionStatus.resource_id == resource_id,
            ProjectionStatus.provider == provider,
        )
        .first()
    )
    if row:
        row.desired_revision = desired_revision
        row.applied_revision = applied_revision
        row.state = state
        row.last_error = error
        row.last_verified_at = datetime.now(timezone.utc)
        db.flush()
        return row

    row = ProjectionStatus(
        tenant_id=tenant_id,
        resource_type=resource_type,
        resource_id=resource_id,
        provider=provider,
        desired_revision=desired_revision,
        applied_revision=applied_revision,
        state=state,
        last_error=error,
        last_verified_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.flush()
    return row


def _resolve_provider_resource_id(
    db: Session,
    provider: str,
    event: OutboxEvent,
) -> str:
    """Prefer provider-side ID from gateway_resources; fall back to Enclave id."""
    if provider == "enclave":
        return event.aggregate_id
    mapped = _registry.get_provider_resource_id(
        db,
        event.tenant_id,
        event.aggregate_type,
        event.aggregate_id,
        provider,
    )
    return mapped or event.aggregate_id


async def _dispatch_to_provider(
    provider: str,
    adapter: Any,
    event: OutboxEvent,
    authz: AuthorizationContext,
    db: Optional[Session] = None,
) -> Dict[str, Any]:
    aggregate_id = event.aggregate_id
    revision = event.revision
    payload = event.payload or {}
    idempotency_key = event.idempotency_key

    # DD-H09：created 不投影內容（檔案可能尚未就緒）；僅 document_processed / updated 可 ingest
    if event.event_type == "created":
        return {
            "status": "skipped",
            "reason": "created_no_content_projection",
            "provider": provider,
        }

    if event.event_type in ("updated", "document_processed"):
        # DD-H09：parse 路徑已 ingest 過 → 只 reconcile／對齊 mapping，禁止再 POST
        if (
            provider == "ragflow"
            and payload.get("ragflow_already_ingested")
            and db is not None
        ):
            provider_rid = (payload.get("ragflow_doc_ids") or [None])[
                0
            ] or _resolve_provider_resource_id(db, provider, event)
            return await adapter.reconcile(
                resource_type=event.aggregate_type,
                resource_id=provider_rid,
                desired_revision=revision,
            )
        # pending projection：改 reconcile，禁止重複 POST ingest
        if db is not None and provider != "enclave":
            pending = (
                db.query(ProjectionStatus)
                .filter(
                    ProjectionStatus.tenant_id == event.tenant_id,
                    ProjectionStatus.resource_type == event.aggregate_type,
                    ProjectionStatus.resource_id == event.aggregate_id,
                    ProjectionStatus.provider == provider,
                    ProjectionStatus.state == "pending",
                )
                .first()
            )
            if pending:
                provider_rid = _resolve_provider_resource_id(db, provider, event)
                return await adapter.reconcile(
                    resource_type=event.aggregate_type,
                    resource_id=provider_rid,
                    desired_revision=revision,
                )
            # mapping 已存在（parse 寫入）→ reconcile
            mapped = _registry.get_provider_resource_id(
                db,
                event.tenant_id,
                event.aggregate_type,
                event.aggregate_id,
                provider,
            )
            if mapped:
                return await adapter.reconcile(
                    resource_type=event.aggregate_type,
                    resource_id=mapped,
                    desired_revision=revision,
                )
        content_uri = payload.get("content_uri", payload.get("file_path", ""))
        content_hash = payload.get("content_hash", "")
        file_type = payload.get("file_type", "pdf")
        meta = dict(payload)
        # ADR-013：payload 未帶 sidecar ID 時（舊事件），以 binding 解析；
        # 不再讀全域環境變數決定租戶歸屬
        if (not meta.get("dataset_id") or not meta.get("kb_id")) and db is not None:
            from app.services.sidecar_binding import (
                resolve_ragflow_dataset_id,
                resolve_weknora_kb_id,
            )

            event_tenant = payload.get("tenant_id")
            if event_tenant:
                if not meta.get("dataset_id"):
                    ds = resolve_ragflow_dataset_id(db, UUID(event_tenant))
                    if ds:
                        meta["dataset_id"] = ds
                if not meta.get("kb_id"):
                    kb = resolve_weknora_kb_id(db, UUID(event_tenant))
                    if kb:
                        meta["kb_id"] = kb
        return await adapter.ingest(
            document_id=UUID(aggregate_id),
            revision=revision,
            content_uri=content_uri,
            content_hash=content_hash,
            file_type=file_type,
            authz=authz,
            metadata=meta,
        )

    provider_resource_id = (
        _resolve_provider_resource_id(db, provider, event)
        if db is not None
        else aggregate_id
    )

    if event.event_type in ("deleted", "revoked", "document_revoked"):
        return await adapter.delete(
            resource_type=event.aggregate_type,
            resource_id=provider_resource_id,
            revision=revision,
            idempotency_key=idempotency_key,
        )

    if event.event_type == "reconcile":
        return await adapter.reconcile(
            resource_type=event.aggregate_type,
            resource_id=provider_resource_id,
            desired_revision=revision,
        )

    return {"status": "skipped", "reason": f"unhandled_event_type:{event.event_type}"}


def _run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


STALE_PROCESSING_SECONDS = 300


def _claim_outbox_events(db: Session) -> list:
    """Claim pending/failed/stale-processing events (SKIP LOCKED on PostgreSQL)."""
    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(seconds=STALE_PROCESSING_SECONDS)
    q = (
        db.query(OutboxEvent)
        .filter(
            (
                OutboxEvent.status.in_(["pending", "failed"])
                & (
                    (OutboxEvent.next_retry_at.is_(None))
                    | (OutboxEvent.next_retry_at <= now)
                )
            )
            | (
                (OutboxEvent.status == "processing")
                & (OutboxEvent.updated_at.isnot(None))
                & (OutboxEvent.updated_at <= stale_before)
            ),
        )
        .order_by(OutboxEvent.created_at)
        .limit(POLL_BATCH_SIZE)
    )
    try:
        bind = db.get_bind()
        dialect = getattr(bind.dialect, "name", "") if bind is not None else ""
        if dialect == "postgresql":
            q = q.with_for_update(skip_locked=True)
    except Exception:
        pass
    events = q.all()
    for event in events:
        event.status = "processing"
        event.attempts = (event.attempts or 0) + 1
        event.updated_at = now
    if events:
        db.flush()
    return events


@celery_app.task(name="tasks.process_outbox", bind=True, max_retries=0)
def process_outbox_batch(self):
    """定期輪詢 outbox_events，處理一批已 claim 的事件。"""
    db: Session = MaintenanceSessionLocal()
    try:
        from app.services.rls import apply_rls_bypass, apply_rls_context

        apply_rls_bypass(
            db,
            actor_identity="celery:process_outbox",
            operation="claim_outbox_batch",
            reason="Claim pending tenant outbox events before tenant-scoped dispatch",
            correlation_id=str(getattr(self.request, "id", "") or "") or None,
        )
        events = _claim_outbox_events(db)
        if not events:
            return {"processed": 0}
        claimed = [(event.id, event.tenant_id) for event in events]
        db.commit()  # commit claim so other workers skip locked rows

        processed = 0
        for event_id, tenant_id in claimed:
            apply_rls_context(db, tenant_id)
            # Re-attach claimed event in a short transaction per event
            event = db.query(OutboxEvent).filter(OutboxEvent.id == event_id).first()
            if not event:
                continue
            try:
                _dispatch_event(db, event)
                processed += 1
                db.commit()
            except Exception as exc:
                logger.error("Outbox event %s dispatch failed: %s", event.id, exc)
                db.rollback()
                event = db.query(OutboxEvent).filter(OutboxEvent.id == event.id).first()
                if event:
                    _handle_failure(db, event, str(exc))
                    db.commit()

        return {"processed": processed}

    except Exception:
        db.rollback()
        logger.exception("process_outbox_batch failed")
        raise
    finally:
        db.close()


def _dispatch_event(db: Session, event: OutboxEvent):
    # Claim already set status=processing + attempts; do not double-increment
    handler_map = {
        "document": _handle_document_event,
        "permission": _handle_permission_event,
        "kb": _handle_kb_event,
        "tenant": _handle_tenant_event,
        "connector": _handle_connector_event,
        "wiki": _handle_wiki_event,
    }

    handler = handler_map.get(event.aggregate_type)
    if handler:
        handler(db, event)
    else:
        logger.warning(
            "No handler for aggregate_type=%s, marking completed", event.aggregate_type
        )
        event.status = "completed"

    db.flush()


def _handle_document_event(db: Session, event: OutboxEvent):
    payload = event.payload or {}
    authz = _authz_from_payload(payload)
    adapters = _get_projection_adapters()
    errors = []

    active_providers = [p for p in PROJECTION_PROVIDERS if adapters.get(p)]
    for provider in active_providers:
        adapter = adapters[provider]
        # 冪等：已 converged 且 revision 相同 → 跳過，避免重複 artifact
        existing_proj = (
            db.query(ProjectionStatus)
            .filter(
                ProjectionStatus.tenant_id == event.tenant_id,
                ProjectionStatus.resource_type == event.aggregate_type,
                ProjectionStatus.resource_id == event.aggregate_id,
                ProjectionStatus.provider == provider,
                ProjectionStatus.state == "converged",
                ProjectionStatus.applied_revision == event.revision,
            )
            .first()
        )
        if existing_proj and event.event_type not in (
            "deleted",
            "revoked",
            "document_revoked",
        ):
            continue
        try:
            result = _run_async(
                _dispatch_to_provider(provider, adapter, event, authz, db=db)
            )
            # Fail-closed: HTTP/stub error payloads must not mark converged
            if isinstance(result, dict):
                if result.get("status") == "error":
                    raise RuntimeError(result.get("error") or "provider_error")
                if event.event_type == "reconcile" and result.get("converged") is False:
                    raise RuntimeError(result.get("error") or "not_converged")
                # DD-H09：created 略過內容投影 — 不可寫成 converged，否則 document_processed 會被跳過
                if (
                    result.get("status") == "skipped"
                    and result.get("reason") == "created_no_content_projection"
                ):
                    continue
            applied_revision = event.revision
            if event.event_type in ("deleted", "revoked", "document_revoked"):
                if isinstance(result, dict) and result.get("status") == "error":
                    raise RuntimeError(result.get("error") or "delete_failed")
                state = "tombstoned"
                _registry.tombstone(
                    db,
                    event.tenant_id,
                    event.aggregate_type,
                    event.aggregate_id,
                    provider=provider,
                )
            else:
                provider_rid = None
                result_status = None
                if isinstance(result, dict):
                    provider_rid = (
                        result.get("provider_resource_id")
                        or (result.get("ragflow_doc_ids") or [None])[0]
                    )
                    result_status = result.get("status")
                # skipped (enclave no-op) = converged; submitted = pending until reconcile
                if result_status == "submitted":
                    state = "pending"
                else:
                    state = "converged"
                _registry.upsert_mapping(
                    db,
                    tenant_id=event.tenant_id,
                    enclave_resource_type=event.aggregate_type,
                    enclave_resource_id=event.aggregate_id,
                    enclave_revision=event.revision,
                    provider=provider,
                    provider_resource_id=provider_rid
                    or (event.aggregate_id if provider == "enclave" else None),
                    provider_revision=applied_revision,
                    checksum=payload.get("content_hash"),
                    state="active" if state == "converged" else "pending",
                )
            _upsert_projection_status(
                db,
                tenant_id=event.tenant_id,
                resource_type=event.aggregate_type,
                resource_id=event.aggregate_id,
                provider=provider,
                desired_revision=event.revision,
                applied_revision=applied_revision,
                state=state,
            )
        except Exception as exc:
            logger.error(
                "Projection dispatch failed provider=%s event=%s: %s",
                provider,
                event.id,
                exc,
            )
            errors.append(f"{provider}:{exc}")
            _upsert_projection_status(
                db,
                tenant_id=event.tenant_id,
                resource_type=event.aggregate_type,
                resource_id=event.aggregate_id,
                provider=provider,
                desired_revision=event.revision,
                applied_revision=0,
                state="error",
                error=str(exc)[:500],
            )

    # Sidecar（非 enclave）失敗必須可重試，不可標 completed 後永遠不再派送
    sidecar_errors = [e for e in errors if not e.startswith("enclave:")]
    if sidecar_errors:
        event.error_message = "; ".join(errors)[:1000]
        raise RuntimeError("; ".join(sidecar_errors))
    if errors and active_providers and len(errors) == len(active_providers):
        raise RuntimeError("; ".join(errors))

    event.status = "completed"
    if errors:
        event.error_message = "; ".join(errors)[:1000]


def _handle_permission_event(db: Session, event: OutboxEvent):
    from app.gateway.authorization import GatewayAuthorizer

    authorizer = GatewayAuthorizer()
    payload = event.payload or {}
    resource_id = payload.get("document_id", event.aggregate_id)
    subject_id = payload.get("subject_id")
    tenant_id = payload.get("tenant_id")
    if subject_id and event.event_type in ("revoked", "deleted"):
        from uuid import UUID

        authorizer.add_deny_entry(
            str(resource_id),
            UUID(subject_id),
            tenant_id=UUID(tenant_id) if tenant_id else None,
        )
    event.status = "completed"


def _handle_connector_event(db: Session, event: OutboxEvent):
    # created / credential_rotated are lifecycle audit events, not implicit
    # sync commands. Interactive sync runs in the API and emits sync_completed;
    # retaining sync_requested supports already-queued legacy async requests.
    if event.event_type == "sync_requested":
        try:
            from uuid import UUID as _UUID

            from app.services.connector_sync import ConnectorSyncService

            ConnectorSyncService().run_sync(db, _UUID(event.aggregate_id))
        except Exception as exc:
            logger.error("Connector outbox handler failed: %s", exc)
            raise
    event.status = "completed"


def _handle_wiki_event(db: Session, event: OutboxEvent):
    payload = event.payload or {}
    if event.event_type == "compiled":
        if os.getenv("WEKNORA_ENABLED", "").lower() == "true":
            from uuid import UUID as _UUID

            from app.gateway.adapters.weknora_http import WeKnoraHTTPAdapter
            from app.gateway.token_provider import build_weknora_token_provider

            adapter = WeKnoraHTTPAdapter(
                base_url=os.getenv("WEKNORA_BASE_URL", "http://localhost:8081"),
                api_key=os.getenv("WEKNORA_API_KEY", ""),
                token_provider=build_weknora_token_provider(),
            )
            kb_id = payload.get("kb_id")
            if not kb_id:
                raise RuntimeError("wiki compiled event missing kb_id")
            result = _run_async(adapter.compile_wiki(_UUID(kb_id)))
            if isinstance(result, dict) and result.get("status") == "error":
                raise RuntimeError(result.get("error") or "wiki_compile_failed")
            _upsert_projection_status(
                db,
                tenant_id=event.tenant_id,
                resource_type="wiki",
                resource_id=event.aggregate_id,
                provider="weknora",
                desired_revision=event.revision,
                applied_revision=event.revision,
                state="converged",
            )
    if event.event_type in ("revoked", "deleted"):
        from uuid import UUID as _UUID

        from app.services.wiki_compiler import WikiCompiler

        WikiCompiler().tombstone_page(db, _UUID(event.aggregate_id))
    if event.event_type == "compile_failed":
        event.status = "completed"
        return
    event.status = "completed"


def _handle_kb_event(db: Session, event: OutboxEvent):
    if event.event_type in ("revision_updated", "updated"):
        payload = event.payload or {}
        kb_id = payload.get("kb_id", event.aggregate_id)
        tenant_id = payload.get("tenant_id")
        if tenant_id:
            from uuid import UUID as _UUID

            from app.services.wiki_compiler import WikiCompiler

            WikiCompiler().compile_kb(
                db,
                _UUID(tenant_id),
                _UUID(kb_id),
                page_type="summary",
            )
    event.status = "completed"


def _handle_tenant_event(db: Session, event: OutboxEvent):
    event.status = "completed"


def _handle_failure(db: Session, event: OutboxEvent, error_message: str):
    event.status = "failed"
    event.error_message = error_message[:1000]

    if event.attempts >= MAX_RETRIES:
        dlq = DeadLetterEvent(
            tenant_id=event.tenant_id,
            original_event_id=event.id,
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id,
            event_type=event.event_type,
            reason=error_message[:1000],
            payload=event.payload,
            attempts=event.attempts,
        )
        db.add(dlq)
        event.status = "dead"
        logger.warning(
            "Event %s moved to dead-letter after %s attempts", event.id, event.attempts
        )
    else:
        backoff_idx = min(event.attempts - 1, len(RETRY_BACKOFF_SECONDS) - 1)
        delay = RETRY_BACKOFF_SECONDS[backoff_idx]
        event.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
        logger.info(
            "Event %s will retry in %ss (attempt %s/%s)",
            event.id,
            delay,
            event.attempts,
            MAX_RETRIES,
        )


# 向後相容：publish_event 本體移至 app.services.outbox_events（避免循環匯入）
from app.services.outbox_events import publish_event  # noqa: E402,F401
