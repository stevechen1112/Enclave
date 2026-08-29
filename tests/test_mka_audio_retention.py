"""MKA audio retention / cost DB-backed contract tests（關閉假綠：正式路徑走 DB）。"""
import inspect
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 - register relationship targets
from app.db.base_class import Base
from app.models.mka import (
    InteractionSession,
    MKAAudioPolicy,
    MKATaskCost,
)
from app.models.permission import Department
from app.models.tenant import Tenant
from app.models.user import User
from app.services.audio_retention import (
    get_cost_summary_db,
    get_policy_db,
    purge_expired_transcripts,
    record_cost_db,
    set_policy_db,
)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        Tenant.__table__,
        Department.__table__,
        User.__table__,
        InteractionSession.__table__,
        MKAAudioPolicy.__table__,
        MKATaskCost.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _tenant(db):
    tenant = Tenant(id=uuid.uuid4(), name=f"tenant-{uuid.uuid4()}")
    user = User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        email=f"{uuid.uuid4()}@test.local",
        hashed_password="not-used",
        role="owner",
        status="active",
    )
    db.add_all([tenant, user])
    db.flush()
    return tenant, user


def _session_row(tenant, user, *, created_at, text="轉寫"):
    return InteractionSession(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        user_id=user.id,
        channel="pwa",
        transcript=text,
        state="completed",
        created_at=created_at,
    )


def test_policy_default_without_db_row(db):
    tenant, _ = _tenant(db)
    policy = get_policy_db(db, tenant.id)
    assert policy.save_audio is False
    assert policy.save_transcript is True
    assert policy.transcript_retention_days == 365
    assert db.query(MKAAudioPolicy).count() == 0  # 預設不落庫


def test_policy_upsert_roundtrip(db):
    tenant, _ = _tenant(db)
    set_policy_db(db, tenant.id, save_audio=True, transcript_retention_days=30)
    policy = get_policy_db(db, tenant.id)
    assert policy.save_audio is True
    assert policy.transcript_retention_days == 30
    set_policy_db(db, tenant.id, save_audio=False)
    assert db.query(MKAAudioPolicy).count() == 1  # upsert 不增生
    assert get_policy_db(db, tenant.id).save_audio is False


def test_cost_record_and_summary_db(db):
    tenant, _ = _tenant(db)
    record_cost_db(
        db, tenant_id=tenant.id, task_type="stt", task_id="s-1",
        stt_cost=0.5, details={"provider": "test"},
    )
    record_cost_db(
        db, tenant_id=tenant.id, task_type="chat", llm_cost=2.0, embedding_cost=0.1,
    )
    other, _ = _tenant(db)
    record_cost_db(db, tenant_id=other.id, task_type="stt", stt_cost=9.9)

    summary = get_cost_summary_db(db, tenant.id)
    assert summary["total_tasks"] == 2
    assert summary["total_cost"] == pytest.approx(2.6)
    assert summary["cost_breakdown"]["stt"] == pytest.approx(0.5)
    assert summary["cost_breakdown"]["llm"] == pytest.approx(2.0)

    stt_only = get_cost_summary_db(db, tenant.id, task_type="stt")
    assert stt_only["total_tasks"] == 1
    assert stt_only["total_cost"] == pytest.approx(0.5)


def test_purge_respects_per_tenant_retention_days(db):
    tenant_a, user_a = _tenant(db)
    tenant_b, user_b = _tenant(db)
    set_policy_db(db, tenant_a.id, transcript_retention_days=30)
    now = datetime(2026, 8, 6)

    old_a = _session_row(tenant_a, user_a, created_at=now - timedelta(days=40))
    new_a = _session_row(tenant_a, user_a, created_at=now - timedelta(days=10))
    old_b = _session_row(tenant_b, user_b, created_at=now - timedelta(days=40))
    db.add_all([old_a, new_a, old_b])
    db.flush()

    result = purge_expired_transcripts(db, now=now)
    # A 保留 30 天 → 40 天的刪；B 無政策用預設 365 天 → 40 天的保留
    assert result["deleted_sessions"] == 1
    remaining = {row.id for row in db.query(InteractionSession).all()}
    assert remaining == {new_a.id, old_b.id}


def test_voice_endpoint_wires_policy_and_cost():
    import app.api.v1.endpoints.voice as voice_endpoint

    source = inspect.getsource(voice_endpoint)
    assert "get_policy_db" in source
    assert "record_cost_db" in source
    assert "transcript_redacted" in source
    assert "VOICE_STT_COST_PER_SECOND" in source


def test_purge_task_registered_in_beat():
    import app.celery_app as celery_module

    source = inspect.getsource(celery_module)
    assert "tasks.purge_mka_retention" in source
    assert "app.tasks.input_capture_tasks" in source


def test_purge_task_uses_rls_bypass():
    import app.tasks.input_capture_tasks as mka_tasks

    source = inspect.getsource(mka_tasks.purge_mka_retention)
    assert "apply_rls_bypass" in source
