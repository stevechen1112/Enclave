"""Outbox idempotency + ACL cache epoch behavior tests."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from app.db.base_class import Base
from app.models.outbox import OutboxEvent, ProjectionStatus
from app.services.outbox_events import publish_event
from app.tasks.outbox_worker import _handle_document_event


@pytest.fixture
def db_session(test_engine):
    import app.models  # noqa: F401
    Base.metadata.create_all(bind=test_engine)
    Session = sessionmaker(bind=test_engine)
    db = Session()
    yield db
    db.close()


def test_publish_event_idempotent(db_session):
    key_payload = {"tenant_id": str(uuid.uuid4())}
    agg = str(uuid.uuid4())
    e1 = publish_event(
        db_session,
        aggregate_type="document",
        aggregate_id=agg,
        event_type="created",
        revision=1,
        payload=key_payload,
    )
    db_session.flush()
    e2 = publish_event(
        db_session,
        aggregate_type="document",
        aggregate_id=agg,
        event_type="created",
        revision=1,
        payload=key_payload,
    )
    db_session.commit()
    assert e1.id == e2.id
    count = (
        db_session.query(OutboxEvent)
        .filter(OutboxEvent.aggregate_id == agg, OutboxEvent.event_type == "created")
        .count()
    )
    assert count == 1


def test_document_projection_skip_when_already_converged(db_session, monkeypatch):
    agg = str(uuid.uuid4())
    event = OutboxEvent(
        aggregate_type="document",
        aggregate_id=agg,
        event_type="created",
        revision=3,
        payload={"tenant_id": str(uuid.uuid4()), "content_hash": "abc"},
        idempotency_key=f"document:{agg}:created:3",
        status="pending",
    )
    db_session.add(event)
    for provider in ("enclave", "ragflow", "weknora", "pipeshub"):
        db_session.add(
            ProjectionStatus(
                resource_type="document",
                resource_id=agg,
                provider=provider,
                desired_revision=3,
                applied_revision=3,
                state="converged",
            )
        )
    db_session.commit()

    calls = []

    async def _fake_dispatch(*args, **kwargs):
        calls.append(1)
        return {"status": "submitted", "provider_resource_id": "x"}

    monkeypatch.setattr(
        "app.tasks.outbox_worker._dispatch_to_provider",
        _fake_dispatch,
    )
    # rebuild adapters path still runs; ensure skip before dispatch
    _handle_document_event(db_session, event)
    db_session.commit()
    assert calls == []
    assert event.status == "completed"


def test_cache_epoch_bump_changes_key(monkeypatch):
    from app.services.kb_retrieval import KnowledgeBaseRetriever
    from app.core.authorization import AuthorizationContext

    class FakeRedis:
        def __init__(self):
            self.store = {"kb:acl_epoch:t1": "1"}

        def get(self, key):
            return self.store.get(key)

        def incr(self, key):
            cur = int(self.store.get(key, "0")) + 1
            self.store[key] = str(cur)
            return cur

        def setex(self, *a, **k):
            return True

        def scan(self, cursor, match=None, count=100):
            return 0, []

        def delete(self, *keys):
            return 0

        def ping(self):
            return True

    r = KnowledgeBaseRetriever()
    fake = FakeRedis()
    r._redis = fake
    tenant = uuid.UUID("00000000-0000-0000-0000-000000000001")
    # patch epoch key tenant string
    fake.store[f"kb:acl_epoch:{tenant}"] = "1"
    authz = AuthorizationContext(
        tenant_id=tenant,
        subject_id=uuid.uuid4(),
        role_ids=["employee"],
        policy_revision=1,
    )
    k1 = r._cache_key(tenant, "q", "hybrid", 5, 0.0, authz)
    r.invalidate_cache(tenant)
    k2 = r._cache_key(tenant, "q", "hybrid", 5, 0.0, authz)
    assert k1 != k2 or fake.store[f"kb:acl_epoch:{tenant}"] == "2"
    # epoch bumped → raw hash input differs → key differs
    assert k1 != k2
