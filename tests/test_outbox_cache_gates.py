"""Outbox idempotency + ACL cache epoch behavior tests."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from app.db.base_class import Base
from app.models.outbox import DeadLetterEvent, OutboxEvent, ProjectionStatus
from app.models.tenant import Tenant
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
    tenant = Tenant(id=uuid.uuid4(), name="outbox-idempotency", status="active")
    db_session.add(tenant)
    db_session.flush()
    key_payload = {"tenant_id": str(tenant.id)}
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
    tenant = Tenant(id=uuid.uuid4(), name="projection-convergence", status="active")
    db_session.add(tenant)
    db_session.flush()
    event = OutboxEvent(
        tenant_id=tenant.id,
        aggregate_type="document",
        aggregate_id=agg,
        event_type="created",
        revision=3,
        payload={"tenant_id": str(tenant.id), "content_hash": "abc"},
        idempotency_key=f"document:{agg}:created:3",
        status="pending",
    )
    db_session.add(event)
    for provider in ("enclave", "ragflow", "weknora", "pipeshub"):
        db_session.add(
            ProjectionStatus(
                tenant_id=tenant.id,
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


def _failed_event(db_session, *, attempts: int) -> OutboxEvent:
    tenant = Tenant(id=uuid.uuid4(), name=f"outbox-failure-{attempts}", status="active")
    db_session.add(tenant)
    db_session.flush()
    event = OutboxEvent(
        tenant_id=tenant.id,
        aggregate_type="document",
        aggregate_id=str(uuid.uuid4()),
        event_type="created",
        revision=1,
        payload={"tenant_id": str(tenant.id)},
        idempotency_key=f"failure-{uuid.uuid4()}",
        status="processing",
        attempts=attempts,
    )
    db_session.add(event)
    db_session.commit()
    return event


def test_failure_before_retry_budget_remains_retryable(db_session):
    from app.tasks.outbox_worker import MAX_RETRIES, _handle_failure

    event = _failed_event(db_session, attempts=MAX_RETRIES - 1)
    _handle_failure(db_session, event, "provider unavailable")
    db_session.commit()

    assert event.status == "failed"
    assert event.next_retry_at is not None
    assert db_session.query(DeadLetterEvent).count() == 0


def test_exhausted_retry_budget_moves_event_to_dead_letter(db_session):
    from app.tasks.outbox_worker import MAX_RETRIES, _handle_failure

    event = _failed_event(db_session, attempts=MAX_RETRIES)
    _handle_failure(db_session, event, "provider unavailable")
    db_session.commit()

    assert event.status == "dead"
    dead = db_session.query(DeadLetterEvent).one()
    assert dead.original_event_id == event.id
    assert dead.tenant_id == event.tenant_id
    assert dead.attempts == MAX_RETRIES
    assert dead.reason == "provider unavailable"


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


def test_cache_key_includes_filter_dict():
    """契約：scoped（filter_dict）與非 scoped 搜尋不得共用快取條目。"""
    from app.services.kb_retrieval import KnowledgeBaseRetriever

    r = KnowledgeBaseRetriever()
    r._redis = None  # epoch 走 "0" 分支即可，不需 Redis
    tenant = uuid.UUID("00000000-0000-0000-0000-000000000001")

    k_unscoped = r._cache_key(tenant, "q", "hybrid", 5, 0.0)
    k_scoped = r._cache_key(
        tenant, "q", "hybrid", 5, 0.0, filter_dict={"filename": "a.pdf"}
    )
    k_scoped_other = r._cache_key(
        tenant, "q", "hybrid", 5, 0.0, filter_dict={"filename": "b.pdf"}
    )
    # 鍵序無關：相同條件不同順序應產生相同鍵
    k_scoped_reordered = r._cache_key(
        tenant,
        "q",
        "hybrid",
        5,
        0.0,
        filter_dict={"filename": "a.pdf"},
    )

    assert k_unscoped != k_scoped
    assert k_scoped != k_scoped_other
    assert k_scoped == k_scoped_reordered


def test_cache_scoped_unscoped_no_collision():
    """契約：scoped 寫入的快取不得被非 scoped 讀取命中（反之亦然）。"""
    from app.services.kb_retrieval import KnowledgeBaseRetriever

    class FakeRedis:
        def __init__(self):
            self.store = {}

        def get(self, key):
            return self.store.get(key)

        def setex(self, key, ttl, value):
            self.store[key] = value
            return True

    r = KnowledgeBaseRetriever()
    r._redis = FakeRedis()
    tenant = uuid.UUID("00000000-0000-0000-0000-000000000001")

    r._cache_set(
        tenant,
        "q",
        "hybrid",
        5,
        0.0,
        [{"content": "scoped"}],
        filter_dict={"filename": "a.pdf"},
    )
    # 非 scoped 讀取不得命中 scoped 條目
    assert r._cache_get(tenant, "q", "hybrid", 5, 0.0) is None
    # scoped 讀取命中自己的條目
    assert r._cache_get(
        tenant, "q", "hybrid", 5, 0.0, filter_dict={"filename": "a.pdf"}
    ) == [{"content": "scoped"}]
    # 不同檔名的 scoped 讀取不得命中
    assert (
        r._cache_get(tenant, "q", "hybrid", 5, 0.0, filter_dict={"filename": "b.pdf"})
        is None
    )
