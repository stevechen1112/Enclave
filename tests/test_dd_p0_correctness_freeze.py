"""DD P0 Correctness Freeze regressions (C01/C02/H01/H05/H09/H12)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import sessionmaker

from app.db.base_class import Base
from app.core.authorization import AuthorizationContext


@pytest.fixture
def db_session(test_engine):
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=test_engine)
    Session = sessionmaker(bind=test_engine)
    db = Session()
    yield db
    db.close()


def _authz(tenant_id, subject_id=None, *, is_superuser=False, role_ids=None):
    return AuthorizationContext(
        tenant_id=tenant_id,
        subject_id=subject_id or uuid.uuid4(),
        role_ids=role_ids or ["member"],
        is_superuser=is_superuser,
        policy_revision=1,
    )


class TestC01KbSearchRequiresAuthz:
    def test_kb_search_endpoint_passes_authz(self):
        """DD-C01: /kb/search must call retriever.search with authz=."""
        import inspect
        from app.api.v1.endpoints import kb as kb_mod

        src = inspect.getsource(kb_mod.search_knowledge_base)
        assert "authz=" in src
        assert "AuthorizationContext.from_user" in src


class TestC02BatchDeleteUsesRevocation:
    def test_batch_delete_uses_revocation_service(self, db_session):
        from app.models.tenant import Tenant
        from app.models.document import Document
        from app.services.document_revocation import DocumentRevocationService

        tenant = Tenant(id=uuid.uuid4(), name="t", plan="free", status="active")
        db_session.add(tenant)
        db_session.flush()
        doc = Document(
            tenant_id=tenant.id,
            filename="a.pdf",
            file_type="pdf",
            status="completed",
        )
        db_session.add(doc)
        db_session.commit()

        actor = uuid.uuid4()
        result = DocumentRevocationService().revoke(
            db_session,
            document_id=doc.id,
            actor_id=actor,
            tenant_id=tenant.id,
            reason="batch_delete",
        )
        db_session.refresh(doc)
        assert result["ok"] is True
        assert doc.tombstoned_at is not None

    def test_batch_delete_endpoint_source_calls_revocation(self):
        import inspect
        from app.api.v1.endpoints import documents as docs_mod

        src = inspect.getsource(docs_mod.batch_delete_documents)
        assert "DocumentRevocationService" in src or "get_document_revocation" in src
        assert "db.delete" not in src


class TestH01GenerateDocumentAcl:
    def test_generate_filters_document_ids_via_pep(self):
        import inspect
        from app.api.v1.endpoints import generate as gen_mod

        src = inspect.getsource(gen_mod.generate_stream)
        assert "get_resource_policy" in src or "load_authorized_document_text" in src
        assert "document_access_denied" in src


class TestH05OutboxClaim:
    def test_claim_marks_processing(self, db_session):
        from app.models.outbox import OutboxEvent
        from app.tasks.outbox_worker import _claim_outbox_events

        agg = str(uuid.uuid4())
        ev = OutboxEvent(
            aggregate_type="document",
            aggregate_id=agg,
            event_type="document_processed",
            revision=1,
            payload={"tenant_id": str(uuid.uuid4())},
            idempotency_key=f"k-{uuid.uuid4()}",
            status="pending",
        )
        db_session.add(ev)
        db_session.commit()

        claimed = _claim_outbox_events(db_session)
        db_session.commit()
        ours = [c for c in claimed if c.aggregate_id == agg]
        assert len(ours) == 1
        assert ours[0].status == "processing"
        assert (ours[0].attempts or 0) >= 1


class TestH09CreatedNoIngest:
    @pytest.mark.asyncio
    async def test_created_skips_content_projection(self):
        from app.models.outbox import OutboxEvent
        from app.tasks.outbox_worker import _dispatch_to_provider

        event = OutboxEvent(
            aggregate_type="document",
            aggregate_id=str(uuid.uuid4()),
            event_type="created",
            revision=1,
            payload={"tenant_id": str(uuid.uuid4()), "file_path": "/tmp/x.pdf"},
            idempotency_key=f"k-{uuid.uuid4()}",
            status="processing",
        )
        adapter = MagicMock()
        adapter.ingest = MagicMock()
        result = await _dispatch_to_provider(
            "ragflow", adapter, event, _authz(uuid.uuid4()), db=None
        )
        assert result["status"] == "skipped"
        assert result["reason"] == "created_no_content_projection"
        adapter.ingest.assert_not_called()

    @pytest.mark.asyncio
    async def test_pending_uses_reconcile_not_ingest(self, db_session):
        from app.models.outbox import OutboxEvent, ProjectionStatus
        from app.tasks.outbox_worker import _dispatch_to_provider

        agg = str(uuid.uuid4())
        event = OutboxEvent(
            aggregate_type="document",
            aggregate_id=agg,
            event_type="document_processed",
            revision=2,
            payload={"tenant_id": str(uuid.uuid4()), "file_path": "/tmp/x.pdf"},
            idempotency_key=f"k-{uuid.uuid4()}",
            status="processing",
        )
        db_session.add(
            ProjectionStatus(
                resource_type="document",
                resource_id=agg,
                provider="ragflow",
                desired_revision=2,
                applied_revision=0,
                state="pending",
            )
        )
        db_session.commit()

        adapter = MagicMock()

        async def _rec(**kwargs):
            return {"status": "ok", "converged": True}

        adapter.reconcile = _rec
        adapter.ingest = MagicMock()
        result = await _dispatch_to_provider(
            "ragflow", adapter, event, _authz(uuid.uuid4()), db=db_session
        )
        assert result.get("converged") is True
        adapter.ingest.assert_not_called()

    @pytest.mark.asyncio
    async def test_ragflow_already_ingested_reconciles(self, db_session):
        from app.models.outbox import OutboxEvent
        from app.tasks.outbox_worker import _dispatch_to_provider

        event = OutboxEvent(
            aggregate_type="document",
            aggregate_id=str(uuid.uuid4()),
            event_type="document_processed",
            revision=1,
            payload={
                "tenant_id": str(uuid.uuid4()),
                "ragflow_already_ingested": True,
                "ragflow_doc_ids": ["rf-1"],
            },
            idempotency_key=f"k-{uuid.uuid4()}",
            status="processing",
        )
        adapter = MagicMock()
        calls = []

        async def _rec(**kwargs):
            calls.append(kwargs)
            return {"status": "ok", "converged": True}

        adapter.reconcile = _rec
        adapter.ingest = MagicMock()
        await _dispatch_to_provider(
            "ragflow", adapter, event, _authz(uuid.uuid4()), db=db_session
        )
        assert len(calls) == 1
        assert calls[0]["resource_id"] == "rf-1"
        adapter.ingest.assert_not_called()


class TestH06WikiFailureNotCompleted:
    def test_wiki_compiled_failure_raises(self, db_session, monkeypatch):
        from app.models.outbox import OutboxEvent
        from app.tasks import outbox_worker as ow

        event = OutboxEvent(
            aggregate_type="wiki",
            aggregate_id=str(uuid.uuid4()),
            event_type="compiled",
            revision=1,
            payload={"kb_id": str(uuid.uuid4())},
            idempotency_key=f"k-{uuid.uuid4()}",
            status="processing",
        )
        db_session.add(event)
        db_session.commit()

        monkeypatch.setenv("WEKNORA_ENABLED", "true")

        class BoomAdapter:
            def __init__(self, *a, **k):
                pass

            async def compile_wiki(self, kb_id):
                return {"status": "error", "error": "weknora_down"}

        monkeypatch.setattr(
            "app.gateway.adapters.weknora_http.WeKnoraHTTPAdapter",
            BoomAdapter,
        )
        with pytest.raises(RuntimeError, match="weknora_down|wiki_compile"):
            ow._handle_wiki_event(db_session, event)


class TestH12ReviewQueueWired:
    def test_watcher_enqueue_when_review_enabled(self, db_session, monkeypatch, tmp_path):
        from app.models.tenant import Tenant
        from app.models.review_item import ReviewItem
        from app.tasks.document_tasks import watcher_ingest_file_task

        tenant_id = uuid.uuid4()
        tenant = Tenant(id=tenant_id, name="r", plan="free", status="active")
        db_session.add(tenant)
        db_session.commit()

        f = tmp_path / "合同_測試_20260101.pdf"
        f.write_bytes(b"%PDF-1.4 fake")

        monkeypatch.setenv("REVIEW_QUEUE_ENABLED", "true")
        monkeypatch.setattr(db_session, "close", lambda: None)
        monkeypatch.setattr(
            "app.tasks.document_tasks.SessionLocal",
            lambda: db_session,
        )

        class FakeProposal:
            file_path = str(f)
            file_name = f.name
            file_size = 10
            file_ext = ".pdf"
            suggested_category = "合約文件"
            suggested_subcategory = "其他合約"
            suggested_tags = {}
            confidence_score = 0.4
            reasoning = "test"
            needs_review = True
            error = None

        class FakeClassifier:
            async def classify_file(self, path):
                return FakeProposal()

        monkeypatch.setattr(
            "app.agent.classifier.get_classifier",
            lambda: FakeClassifier(),
        )

        result = watcher_ingest_file_task.run(
            str(f),
            str(tenant_id),
            str(uuid.uuid4()),
            skip_if_current=False,
            skip_review=False,
        )
        assert result["status"] == "queued_for_review"
        count = (
            db_session.query(ReviewItem)
            .filter(ReviewItem.tenant_id == tenant_id)
            .count()
        )
        assert count == 1
