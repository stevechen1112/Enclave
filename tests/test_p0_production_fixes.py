"""Regression tests for P0 production defects found in plan audit."""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest


class TestPipesHubAsyncResyncNoFalseComplete:
    @pytest.mark.asyncio
    async def test_resync_without_mock_is_submitted_not_completed(self, monkeypatch):
        from app.gateway.adapters.pipeshub_http import PipesHubHTTPAdapter

        adapter = PipesHubHTTPAdapter(base_url="http://pipeshub.test", api_key="k")

        class FakeResp:
            def __init__(self, code, body):
                self.status_code = code
                self._body = body
                self.text = str(body)

            def json(self):
                return self._body

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, *a, **k):
                return FakeResp(200, {"data": [{"connectorId": "c1", "connectorType": "SHAREPOINT ONLINE"}]})

            async def post(self, *a, **k):
                return FakeResp(202, {"ok": True})

        monkeypatch.setattr(
            "app.gateway.adapters.pipeshub_http.make_httpx_client",
            lambda **kw: FakeClient(),
        )
        result = await adapter.sync_connector("sharepoint", {"site_url": "https://x"})
        assert result["status"] == "submitted"
        assert result["resources"] == []
        assert "pending" in result.get("mode", "")


class TestConnectorSyncSkipsEmptyReconcile:
    def test_submitted_does_not_tombstone(self, test_engine, monkeypatch):
        import app.models  # noqa: F401
        from app.db.base_class import Base
        from sqlalchemy.orm import sessionmaker
        from app.models.tenant import Tenant
        from app.models.connector import ConnectorInstance
        from app.models.document import Document
        from app.services.connector_sync import ConnectorSyncService

        Base.metadata.create_all(bind=test_engine)
        Session = sessionmaker(bind=test_engine)
        db = Session()
        try:
            tenant = Tenant(id=uuid.uuid4(), name="P0", plan="free", status="active")
            db.add(tenant)
            db.flush()
            conn = ConnectorInstance(
                tenant_id=tenant.id, connector_type="sharepoint", name="sp",
                config_json={"site_url": "https://x"}, status="active",
            )
            db.add(conn)
            db.flush()
            doc = Document(
                tenant_id=tenant.id, filename="keep.pdf", file_type="pdf",
                status="completed", source_system="sharepoint",
                source_record_id="rec-1",
            )
            db.add(doc)
            db.commit()

            async def fake_fetch(connector, full_reindex=False):
                return {
                    "status": "submitted",
                    "mode": "pipeshub_resync_pending",
                    "resources": [],
                    "acl_entries": [],
                }

            svc = ConnectorSyncService()
            monkeypatch.setattr(svc, "_fetch_remote_sync", fake_fetch)
            out = svc.run_sync(db, conn.id, materialize=True)
            assert out["status"] == "submitted"
            assert out["lifecycle"].get("pending_remote") is True
            still = db.query(Document).filter(Document.id == doc.id).first()
            assert still.tombstoned_at is None
        finally:
            db.close()


class TestOutboxResolvesProviderId:
    def test_resolve_prefers_mapping(self, test_engine):
        import app.models  # noqa: F401
        from app.db.base_class import Base
        from sqlalchemy.orm import sessionmaker
        from app.models.outbox import OutboxEvent
        from app.gateway.resource_registry import ResourceRegistry
        from app.tasks.outbox_worker import _resolve_provider_resource_id

        Base.metadata.create_all(bind=test_engine)
        Session = sessionmaker(bind=test_engine)
        db = Session()
        try:
            enclave_id = str(uuid.uuid4())
            ResourceRegistry().upsert_mapping(
                db,
                enclave_resource_type="document",
                enclave_resource_id=enclave_id,
                enclave_revision=1,
                provider="ragflow",
                provider_resource_id="rf-doc-99",
                state="active",
            )
            db.commit()
            event = OutboxEvent(
                aggregate_type="document",
                aggregate_id=enclave_id,
                event_type="deleted",
                revision=2,
                payload={},
                idempotency_key=f"document:{enclave_id}:deleted:2",
                status="pending",
            )
            assert _resolve_provider_resource_id(db, "ragflow", event) == "rf-doc-99"
            assert _resolve_provider_resource_id(db, "enclave", event) == enclave_id
        finally:
            db.close()


class TestGraphAclNotAllowAll:
    def test_entity_without_source_denied_for_employee(self, test_engine):
        import app.models  # noqa: F401
        from app.db.base_class import Base
        from sqlalchemy.orm import sessionmaker
        from app.models.tenant import Tenant
        from app.services.graph_service import GraphService
        from app.core.authorization import AuthorizationContext

        Base.metadata.create_all(bind=test_engine)
        Session = sessionmaker(bind=test_engine)
        db = Session()
        try:
            tenant = Tenant(id=uuid.uuid4(), name="G", plan="free", status="active")
            db.add(tenant)
            db.flush()
            svc = GraphService()
            ent = svc.upsert_entity(
                db, tenant_id=tenant.id, name="orphan", entity_type="thing",
            )
            db.commit()
            authz = AuthorizationContext(
                tenant_id=tenant.id, subject_id=uuid.uuid4(),
                role_ids=["employee"], policy_revision=1,
            )
            assert svc._entity_allowed(ent, authz, db=db) is False
            hits = svc.search_entities(db, tenant.id, "orphan", authz)
            assert hits == []
        finally:
            db.close()


class TestPipesHubPollAfterResync:
    @pytest.mark.asyncio
    async def test_poll_returns_resources_when_available(self, monkeypatch):
        from app.gateway.adapters.pipeshub_http import PipesHubHTTPAdapter

        adapter = PipesHubHTTPAdapter(base_url="http://pipeshub.test", api_key="k")
        calls = {"n": 0}

        class FakeResp:
            def __init__(self, code, body):
                self.status_code = code
                self._body = body
                self.text = str(body)

            def json(self):
                return self._body

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url, **k):
                calls["n"] += 1
                if "connectors" in url and "records" in url:
                    return FakeResp(200, {
                        "data": [{"id": "r1", "name": "Doc", "checksum": "abc"}],
                    })
                return FakeResp(404, {})

            async def post(self, *a, **k):
                return FakeResp(202, {"ok": True})

        monkeypatch.setattr(
            "app.gateway.adapters.pipeshub_http.make_httpx_client",
            lambda **kw: FakeClient(),
        )
        # bypass instance resolve by injecting id
        async def resolve(*a, **k):
            return "c1"
        monkeypatch.setattr(adapter, "_resolve_pipeshub_connector_id", resolve)
        monkeypatch.setenv("PIPESHUB_POLL_AFTER_RESYNC", "true")
        result = await adapter.sync_connector(
            "sharepoint",
            {"site_url": "https://x", "poll_attempts": 1, "poll_delay_seconds": 0},
        )
        assert result["status"] == "completed"
        assert result["mode"] == "pipeshub_resync_polled"
        assert result["resources"][0]["source_record_id"] == "r1"


class TestOAuthTokenExchangeHelper:
    def test_token_endpoint_and_missing_secret(self):
        from app.services.connector_schemas import oauth_token_endpoint, exchange_oauth_code
        assert "microsoftonline" in oauth_token_endpoint("sharepoint", {})
        assert "googleapis" in oauth_token_endpoint("google_drive", {})
        with pytest.raises(ValueError, match="client_id"):
            exchange_oauth_code(
                "sharepoint", code="x", redirect_uri="http://cb",
                client_id="", client_secret="",
            )


class TestDocumentProcessedOutboxCommits:
    def test_publish_event_persists_after_commit(self, test_engine):
        import app.models  # noqa: F401
        from app.db.base_class import Base
        from sqlalchemy.orm import sessionmaker
        from app.services.outbox_events import publish_event
        from app.models.outbox import OutboxEvent

        Base.metadata.create_all(bind=test_engine)
        Session = sessionmaker(bind=test_engine)
        db = Session()
        try:
            doc_id = str(uuid.uuid4())
            publish_event(
                db,
                aggregate_type="document",
                aggregate_id=doc_id,
                event_type="document_processed",
                revision=1,
                payload={"tenant_id": str(uuid.uuid4())},
            )
            db.commit()
            found = (
                db.query(OutboxEvent)
                .filter(OutboxEvent.aggregate_id == doc_id)
                .first()
            )
            assert found is not None
            assert found.event_type == "document_processed"
            assert found.status == "pending"
        finally:
            db.close()
