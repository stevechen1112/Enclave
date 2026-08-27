"""Gate 4: deterministic synthetic Demo seed, verification, and reset."""
from __future__ import annotations

import uuid
from copy import deepcopy
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.demo.manifest import DEMO_PERSONAS, DEMO_TENANT_ID
from app.services.demo_tenant import (
    purge_demo_tenant,
    reset_demo_tenant,
    seed_demo_tenant,
    verify_demo_tenant,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def isolated_demo_catalog(monkeypatch):
    """Avoid collisions with auth tests that intentionally use demo.mka emails."""
    original = deepcopy(DEMO_PERSONAS)
    for persona, spec in DEMO_PERSONAS.items():
        monkeypatch.setitem(spec, "email", f"{persona}@gate4.synthetic.invalid")
    yield
    for persona, spec in original.items():
        DEMO_PERSONAS[persona].update(spec)


def test_seed_verify_and_transactional_reset(test_engine, isolated_demo_catalog):
    Session = sessionmaker(bind=test_engine)
    db = Session()
    try:
        first = seed_demo_tenant(db)
        db.flush()
        verified = verify_demo_tenant(db)
        assert first["tenant_id"] == str(DEMO_TENANT_ID)
        assert first["personas"] == 6
        assert first["documents"] == 5
        assert verified["ok"] is True
        assert all(verified["checks"].values())

        # Idempotent seed keeps one exact corpus.
        seed_demo_tenant(db)
        db.flush()
        verified_again = verify_demo_tenant(db)
        assert verified_again["counts"] == {"users": 6, "documents": 5}

        reset = reset_demo_tenant(db)
        db.flush()
        assert reset["deleted_rows"] > 0
        assert verify_demo_tenant(db)["ok"] is True
    finally:
        db.rollback()
        db.close()


def test_purge_refuses_real_tenant(test_engine):
    from app.models.tenant import Tenant

    Session = sessionmaker(bind=test_engine)
    db = Session()
    try:
        tenant = db.query(Tenant).filter(Tenant.id == DEMO_TENANT_ID).first()
        if tenant is None:
            tenant = Tenant(
                id=DEMO_TENANT_ID,
                name="Real Customer",
                plan="enterprise",
                status="active",
                is_demo=False,
            )
            db.add(tenant)
        else:
            tenant.name = "Real Customer"
            tenant.is_demo = False
        db.flush()
        with pytest.raises(RuntimeError, match="refusing to purge"):
            purge_demo_tenant(db)
    finally:
        db.rollback()
        db.close()


def test_verify_rejects_extra_noncanonical_demo_content(
    test_engine, isolated_demo_catalog
):
    from app.models.mka import SceneRegistry

    Session = sessionmaker(bind=test_engine)
    db = Session()
    try:
        seed_demo_tenant(db)
        db.add(
            SceneRegistry(
                id=uuid.uuid4(),
                tenant_id=DEMO_TENANT_ID,
                token="UNEXPECTED-DEMO-SCENE",
                label="unexpected",
                active=True,
            )
        )
        db.flush()
        result = verify_demo_tenant(db)
        assert result["ok"] is False
        assert result["checks"]["exact_scene"] is False
    finally:
        db.rollback()
        db.close()


@pytest.mark.asyncio
async def test_all_six_seeded_doors_login_and_bootstrap(
    client: AsyncClient,
    test_engine,
    isolated_demo_catalog,
    monkeypatch: pytest.MonkeyPatch,
):
    Session = sessionmaker(bind=test_engine)
    db = Session()
    try:
        seed_demo_tenant(db)
        db.commit()
    finally:
        db.close()

    monkeypatch.setattr(settings, "DEMO_LOGIN_ENABLED", True)
    monkeypatch.setattr(settings, "DEMO_TENANT_ID", str(DEMO_TENANT_ID))
    monkeypatch.setattr(settings, "DEMO_ADMIN_EMAIL", DEMO_PERSONAS["admin"]["email"])
    expected_roles = {
        "sales": "sales",
        "field": "equipment",
        "master": "master",
        "newcomer": "newcomer",
        "viewer": None,
        "admin": "supervisor",
    }
    try:
        for persona, expected_role in expected_roles.items():
            login = await client.post(
                "/api/v1/auth/login/demo", json={"persona": persona}
            )
            assert login.status_code == 200, (persona, login.text)
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
            bootstrap = await client.get("/api/v1/experience/bootstrap", headers=headers)
            assert bootstrap.status_code == 200, (persona, bootstrap.text)
            body = bootstrap.json()
            assert body["demo_mode"] is True
            assert body["user"]["tenant_id"] == str(DEMO_TENANT_ID)
            assert body["user"]["is_superuser"] is False
            active_role = body.get("active_job_role")
            assert (active_role or {}).get("role_key") == expected_role
            if persona in {"sales", "field", "master", "newcomer", "admin"}:
                assert body["workspace_entries"], persona
            else:
                assert body["workspace_entries"] == []
    finally:
        cleanup = Session()
        try:
            purge_demo_tenant(cleanup)
            cleanup.commit()
        finally:
            cleanup.close()


def test_public_demo_assets_do_not_reintroduce_shared_credentials():
    """Release-facing Demo paths must use persona doors, never shared passwords."""
    shared_password_marker = "Demo" + "12345"
    release_paths = [
        ROOT / "app",
        ROOT / "frontend" / "src",
        ROOT / "docs" / "MKA_DEMO_QUESTION_SET.md",
        ROOT / "docs" / "runbooks" / "SYNTHETIC_DEMO_TENANT.md",
        ROOT / "scripts" / "demo_v3_walkthrough.py",
        ROOT / "scripts" / "diag_bootstrap.sh",
        ROOT / "scripts" / "probe_demo_alignment.sh",
        ROOT / "scripts" / "verify_deploy_api.sh",
        ROOT / "scripts" / "verify_parse_text.sh",
        ROOT / "scripts" / "verify_review_fixes.sh",
    ]
    offenders: list[str] = []
    for candidate in release_paths:
        files = candidate.rglob("*") if candidate.is_dir() else [candidate]
        for path in files:
            if not path.is_file() or path.suffix not in {".py", ".ts", ".tsx", ".md", ".sh"}:
                continue
            if shared_password_marker in path.read_text(encoding="utf-8"):
                offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == []


def test_legacy_demo_logins_are_retired_without_deleting_history(test_engine):
    from app.core.security import get_password_hash
    from app.models.maintenance_audit import PlatformMaintenanceAudit
    from app.models.tenant import Tenant
    from app.models.user import User
    from scripts.retire_legacy_demo_logins import (
        audit_legacy_demo_logins,
        disable_legacy_demo_logins,
    )

    PlatformMaintenanceAudit.__table__.create(bind=test_engine, checkfirst=True)
    Session = sessionmaker(bind=test_engine)
    db = Session()
    try:
        tenant = Tenant(
            id=uuid.uuid4(),
            name="Retired Demo History",
            plan="enterprise",
            status="active",
            is_demo=False,
        )
        user = User(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            email="field@demo.mka",
            full_name="Legacy field demo",
            hashed_password=get_password_hash("legacy-test-password"),
            role="employee",
            status="active",
            is_superuser=False,
        )
        db.add_all([tenant, user])
        db.flush()
        old_hash = user.hashed_password

        assert len(audit_legacy_demo_logins(db)) == 1
        result = disable_legacy_demo_logins(db)

        assert result[0]["status"] == "inactive"
        assert db.get(User, user.id) is not None
        assert user.hashed_password != old_hash
    finally:
        db.rollback()
        db.close()
