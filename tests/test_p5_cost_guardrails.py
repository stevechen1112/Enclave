from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.db.base_class import Base
from app.models.asset import AssetRevision, SourceAsset
from app.models.audit import UsageRecord
from app.models.document import Document
from app.models.mka import MKATaskCost
from app.models.permission import Department
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.tenant import QuotaUpdate
from app.services.cost_guardrails import (
    build_tenant_cost_report,
    check_cost_guardrail,
    media_cost_usd,
    query_reservation_cost_usd,
    reserve_media_cost,
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
        SourceAsset.__table__,
        AssetRevision.__table__,
        Document.__table__,
        UsageRecord.__table__,
        MKATaskCost.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _tenant(db, *, limit=10.0):
    tenant = Tenant(
        id=uuid4(),
        name=f"tenant-{uuid4()}",
        monthly_cost_limit_usd=limit,
    )
    user = User(
        id=uuid4(),
        tenant_id=tenant.id,
        email=f"{uuid4()}@example.invalid",
        hashed_password="x",
        role="owner",
        status="active",
    )
    db.add_all([tenant, user])
    db.flush()
    return tenant, user


def _asset(db, tenant, user, *, kind, duration_ms, byte_size):
    asset = SourceAsset(
        tenant_id=tenant.id,
        asset_kind=kind,
        title=f"{kind}-{uuid4()}",
        source_system="upload",
        current_revision=1,
        status="active",
        created_by=user.id,
    )
    db.add(asset)
    db.flush()
    db.add(
        AssetRevision(
            tenant_id=tenant.id,
            asset_id=asset.id,
            revision=1,
            media_type=f"{kind}/test",
            content_uri=f"s3://test/{asset.id}",
            content_hash=uuid4().hex * 2,
            byte_size=byte_size,
            duration_ms=duration_ms,
            ingestion_status="ready",
            created_by=user.id,
        )
    )


def test_cost_units_are_explicit_and_media_estimates_are_duration_based():
    assert media_cost_usd("audio", 3_600_000) == 0.36
    assert media_cost_usd("video", 3_600_000) == 1.2
    assert query_reservation_cost_usd() == 0.0025
    with pytest.raises(ValueError, match="unsupported"):
        media_cost_usd("document", 1000)
    with pytest.raises(ValidationError):
        QuotaUpdate(monthly_cost_limit_usd=-0.01)


def test_media_reservation_blocks_before_unbounded_overage(db):
    tenant, _user = _tenant(db, limit=0.3)
    denied = reserve_media_cost(
        db,
        tenant_id=tenant.id,
        media_kind="audio",
        duration_ms=3_600_000,
        task_id="audio-denied",
    )
    assert denied["allowed"] is False
    assert db.query(MKATaskCost).count() == 0

    tenant.monthly_cost_limit_usd = 0.4
    allowed = reserve_media_cost(
        db,
        tenant_id=tenant.id,
        media_kind="audio",
        duration_ms=3_600_000,
        task_id="audio-allowed",
    )
    assert allowed["allowed"] is True
    assert allowed["reserved_cost_usd"] == 0.36
    assert db.query(MKATaskCost).count() == 1
    assert (
        check_cost_guardrail(db, tenant.id, additional_cost_usd=0.05)["allowed"]
        is False
    )


def test_tenant_cost_report_has_all_four_units_and_is_tenant_scoped(db):
    tenant, user = _tenant(db, limit=5.0)
    other, other_user = _tenant(db, limit=5.0)
    _asset(db, tenant, user, kind="audio", duration_ms=3_600_000, byte_size=1024**3)
    _asset(db, tenant, user, kind="video", duration_ms=1_800_000, byte_size=1024**3)
    _asset(
        db,
        other,
        other_user,
        kind="video",
        duration_ms=9_000_000,
        byte_size=9 * 1024**3,
    )
    db.add_all(
        [
            UsageRecord(
                tenant_id=tenant.id,
                user_id=user.id,
                action_type="chat_query",
                input_tokens=100,
                estimated_cost_usd=0.1,
            ),
            UsageRecord(
                tenant_id=other.id,
                user_id=other_user.id,
                action_type="chat_query",
                estimated_cost_usd=4.0,
            ),
        ]
    )
    db.flush()

    report = build_tenant_cost_report(db, tenant.id)
    rows = {row["unit"]: row for row in report["unit_reports"]}
    assert set(rows) == {
        "storage_gb_month",
        "audio_hour",
        "video_hour",
        "queries_1000",
    }
    assert rows["storage_gb_month"]["usage"] == 2.0
    assert rows["audio_hour"]["usage"] == 1.0
    assert rows["video_hour"]["usage"] == 0.5
    assert rows["queries_1000"]["usage"] == 0.001
    assert report["tracked_cost_usd"] == 0.1


def test_cost_report_counts_only_unprojected_legacy_document_bytes(db):
    tenant, user = _tenant(db)
    _asset(
        db,
        tenant,
        user,
        kind="document",
        duration_ms=0,
        byte_size=1024**3,
    )
    canonical_asset_id = (
        db.query(SourceAsset.id).filter_by(tenant_id=tenant.id).scalar()
    )
    db.add_all(
        [
            Document(
                tenant_id=tenant.id,
                filename="projected.pdf",
                file_size=1024**3,
                source_asset_id=canonical_asset_id,
            ),
            Document(
                tenant_id=tenant.id,
                filename="legacy.pdf",
                file_size=512 * 1024**2,
                source_asset_id=None,
            ),
        ]
    )
    db.flush()

    report = build_tenant_cost_report(db, tenant.id)
    rows = {row["unit"]: row for row in report["unit_reports"]}
    assert rows["storage_gb_month"]["usage"] == 1.5
