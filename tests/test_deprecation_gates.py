from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request
from starlette.testclient import TestClient

from app.api.v1.endpoints.deprecations import (
    LegacyUsageRequest,
    deprecation_report,
    record_legacy_usage,
)
from app.main import app
from app.middleware.versioning import APIVersionMiddleware, record_legacy_api_usage
from app.models.audit import AuditLog
from app.models.tenant import Tenant
from app.models.user import User
from app.platform.deprecations import (
    SURFACE_BY_KEY,
    SURFACES,
    DeprecationSurface,
    get_deprecation_surface,
    match_api_surface,
)
from app.services.legacy_retirement import (
    build_signed_removal_report,
    evaluate_stage_transition,
    verify_signed_removal_report,
)


def test_deprecation_registry_is_unique_and_replacements_are_absolute():
    assert len(SURFACE_BY_KEY) == len(SURFACES)
    assert all(surface.legacy_path.startswith("/") for surface in SURFACES)
    assert all(surface.replacement_path.startswith("/") for surface in SURFACES)
    assert (
        get_deprecation_surface("frontend.documents").replacement_path
        == "/knowledge/assets"
    )
    assert get_deprecation_surface("not-registered") is None
    assert match_api_surface("/api/v1/documents/abc").key == "api.documents"
    assert match_api_surface("/api/v1/media/videos/abc").key == "api.video"
    assert (
        match_api_surface("/api/v1/media/video-artifacts/abc/review").key
        == "api.video_artifacts"
    )
    assert match_api_surface("/api/v1/knowledge/assets") is None


def test_observe_stage_cannot_remove_even_with_zero_traffic():
    surface = get_deprecation_surface("frontend.documents")
    assert surface is not None
    assert (
        surface.removal_eligible(
            last_used_at=None, now=datetime(2026, 10, 1, tzinfo=UTC)
        )
        is False
    )


def test_warn_stage_requires_full_zero_traffic_window():
    surface = DeprecationSurface(
        key="test.legacy",
        kind="frontend_route",
        legacy_path="/old",
        replacement_path="/new",
        stage="warn",
        observation_started_at=date(2026, 8, 1),
        zero_traffic_days=30,
    )
    now = datetime(2026, 9, 15, tzinfo=UTC)
    assert surface.removal_eligible(last_used_at=None, now=now)
    assert not surface.removal_eligible(last_used_at=now - timedelta(days=5), now=now)


def test_fastapi_has_no_duplicate_method_path_registrations():
    routes: dict[tuple[str, str], list[str]] = defaultdict(list)
    for route in app.routes:
        for method in getattr(route, "methods", ()):
            routes[(method, route.path)].append(route.name)
    duplicates = {key: names for key, names in routes.items() if len(names) > 1}
    assert duplicates == {}
    # Keep this platform-level gate independent from optional product packs.
    # MKA route presence/absence is covered explicitly by test_pack_runtime.py.
    assert routes[("GET", "/api/v1/knowledge/assets")] == ["list_assets"]


def test_legacy_usage_is_validated_and_reported_per_tenant():
    engine = create_engine("sqlite://")
    Tenant.__table__.create(engine)
    User.__table__.create(engine)
    AuditLog.__table__.create(engine)
    db = sessionmaker(bind=engine)()
    try:
        tenant = Tenant(name="legacy-audit")
        db.add(tenant)
        db.flush()
        user = User(
            tenant_id=tenant.id,
            email=f"{uuid4().hex}@example.invalid",
            hashed_password="x",
            role="admin",
            status="active",
        )
        db.add(user)
        db.flush()
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/",
                "headers": [],
                "client": ("127.0.0.1", 1),
            }
        )
        assert record_legacy_usage(
            LegacyUsageRequest(key="frontend.documents", client_path="/documents"),
            request,
            db,
            user,
        ) == {"recorded": True}
        report = deprecation_report(db, user)
        row = next(item for item in report if item["key"] == "frontend.documents")
        assert row["hit_count_30d"] == 1
        assert row["last_used_at"] is not None
        assert row["removal_eligible"] is False
        with pytest.raises(HTTPException):
            record_legacy_usage(
                LegacyUsageRequest(key="unknown.surface"), request, db, user
            )
    finally:
        db.close()
        engine.dispose()


def test_api_legacy_telemetry_is_tenant_scoped():
    engine = create_engine("sqlite://")
    Tenant.__table__.create(engine)
    User.__table__.create(engine)
    AuditLog.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    db = factory()
    try:
        tenant = Tenant(name="api-legacy")
        db.add(tenant)
        db.flush()
        user = User(
            tenant_id=tenant.id,
            email=f"{uuid4().hex}@example.invalid",
            hashed_password="x",
            role="admin",
            status="active",
        )
        db.add(user)
        db.commit()
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/v1/documents/1",
                "query_string": b"",
                "headers": [],
                "client": ("127.0.0.1", 1),
                "scheme": "http",
                "server": ("test", 80),
            }
        )
        surface = get_deprecation_surface("api.documents")
        assert surface is not None
        assert record_legacy_api_usage(
            surface=surface,
            user=user,
            request=request,
            status_code=200,
            session_factory=factory,
        )
        row = db.query(AuditLog).filter(AuditLog.tenant_id == tenant.id).one()
        assert row.target_id == "api.documents"
        assert row.detail_json["request_path"] == "/api/v1/documents/1"
    finally:
        db.close()
        engine.dispose()


def test_precise_deprecation_headers_do_not_deprecate_all_v1():
    client = TestClient(app)
    legacy = client.get("/api/v1/documents/supported-formats")
    assert legacy.headers["Deprecation"] == "true"
    assert legacy.headers["X-Enclave-Deprecation-Key"] == "api.documents"
    assert (
        legacy.headers["Link"] == '</api/v1/knowledge/assets>; rel="successor-version"'
    )
    stable = client.get("/api/v1/experience/bootstrap")
    assert stable.headers["X-API-Version"] == "v1"
    assert "Deprecation" not in stable.headers


def test_disable_stage_returns_gone_before_legacy_handler(monkeypatch):
    disabled = DeprecationSurface(
        key="api.disabled",
        kind="api_route",
        legacy_path="/old",
        replacement_path="/new",
        stage="disable",
        observation_started_at=date(2026, 1, 1),
    )
    monkeypatch.setattr(
        "app.middleware.versioning.match_api_surface", lambda _path: disabled
    )
    mini = FastAPI()
    mini.add_middleware(APIVersionMiddleware)
    mini.get("/old")(lambda: {"should_not": "run"})
    response = TestClient(mini).get("/old")
    assert response.status_code == 410
    assert response.json()["replacement"] == "/new"
    assert response.headers["Sunset"]


def test_signed_global_report_cannot_claim_observe_stage_is_eligible():
    engine = create_engine("sqlite://")
    Tenant.__table__.create(engine)
    User.__table__.create(engine)
    AuditLog.__table__.create(engine)
    db = sessionmaker(bind=engine)()
    key = "test-signing-key-with-at-least-32-characters"
    try:
        tenant = Tenant(name="active", status="active")
        db.add(tenant)
        db.commit()
        report = build_signed_removal_report(
            db, signing_key=key, now=datetime(2026, 10, 1, tzinfo=UTC)
        )
        assert report["status"] == "HOLD"
        assert report["removal_eligible"] is False
        assert report["active_tenant_count"] == 1
        assert verify_signed_removal_report(report, signing_key=key)
        warn = evaluate_stage_transition(
            surface_key="frontend.documents",
            current_stage="observe",
            target_stage="warn",
            report=report,
            signing_key=key,
            tenant_notice_acknowledged=True,
        )
        assert warn["status"] == "PASS"
        disable = evaluate_stage_transition(
            surface_key="frontend.documents",
            current_stage="observe",
            target_stage="disable",
            report=report,
            signing_key=key,
            tenant_notice_acknowledged=True,
        )
        assert disable["status"] == "HOLD"
        assert "cannot be skipped" in " ".join(disable["errors"])
        assert "zero-traffic" in " ".join(disable["errors"])
        missing_surface = evaluate_stage_transition(
            surface_key="not.in.report",
            current_stage="observe",
            target_stage="warn",
            report=report,
            signing_key=key,
            tenant_notice_acknowledged=True,
        )
        assert missing_surface["status"] == "HOLD"
        assert "exactly one" in " ".join(missing_surface["errors"])
        report["status"] = "ELIGIBLE"
        assert not verify_signed_removal_report(report, signing_key=key)
    finally:
        db.close()
        engine.dispose()


def test_transition_is_scoped_to_one_surface_across_all_tenants(monkeypatch):
    engine = create_engine("sqlite://")
    Tenant.__table__.create(engine)
    User.__table__.create(engine)
    AuditLog.__table__.create(engine)
    db = sessionmaker(bind=engine)()
    key = "test-signing-key-with-at-least-32-characters"
    selected = DeprecationSurface(
        key="test.selected",
        kind="frontend_route",
        legacy_path="/selected-old",
        replacement_path="/selected-new",
        stage="warn",
        observation_started_at=date(2026, 8, 1),
    )
    unrelated = DeprecationSurface(
        key="test.unrelated",
        kind="frontend_route",
        legacy_path="/unrelated-old",
        replacement_path="/unrelated-new",
        stage="observe",
        observation_started_at=date(2026, 8, 1),
    )
    monkeypatch.setattr(
        "app.services.legacy_retirement.SURFACES", (selected, unrelated)
    )
    monkeypatch.setattr(
        "app.services.legacy_retirement.get_deprecation_surface",
        lambda key_: selected if key_ == selected.key else None,
    )
    try:
        db.add(Tenant(name="active", status="active"))
        db.commit()
        report = build_signed_removal_report(
            db, signing_key=key, now=datetime(2026, 10, 1, tzinfo=UTC)
        )
        assert report["status"] == "HOLD"
        result = evaluate_stage_transition(
            surface_key=selected.key,
            current_stage="warn",
            target_stage="disable",
            report=report,
            signing_key=key,
            tenant_notice_acknowledged=True,
        )
        assert result == {"status": "PASS", "errors": []}
    finally:
        db.close()
        engine.dispose()
