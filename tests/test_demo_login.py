"""Passwordless demo-door authentication and its read-only admin boundary."""

from __future__ import annotations

import uuid
from copy import deepcopy

import pytest
from httpx import AsyncClient
from jose import jwt
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.core.security import get_password_hash
from app.demo.manifest import DEMO_PERSONAS
from app.models.mka import JobRole, UserJobRoleAssignment
from app.models.tenant import Tenant
from app.models.user import User


@pytest.fixture(autouse=True)
def isolated_demo_login_manifest(monkeypatch: pytest.MonkeyPatch):
    """Keep endpoint fixtures from claiming the canonical seeded identities."""
    original = deepcopy(DEMO_PERSONAS)
    for persona, spec in DEMO_PERSONAS.items():
        monkeypatch.setitem(
            spec,
            "email",
            f"{persona}-login-fixture@demo.enclave.invalid",
        )
    monkeypatch.setattr(settings, "DEMO_ADMIN_EMAIL", DEMO_PERSONAS["admin"]["email"])
    yield
    for persona, spec in original.items():
        DEMO_PERSONAS[persona].update(spec)


def _seed_demo_identity(test_engine, persona: str) -> uuid.UUID:
    specs = {
        "sales": (DEMO_PERSONAS["sales"]["email"], "employee", False, "sales"),
        "admin": (DEMO_PERSONAS["admin"]["email"], "owner", False, "supervisor"),
    }
    email, security_role, is_superuser, job_role_key = specs[persona]
    Session = sessionmaker(bind=test_engine)
    db = Session()
    try:
        tenant = db.query(Tenant).filter(Tenant.name == "Demo Login Test Tenant").first()
        if tenant is None:
            tenant = Tenant(
                id=uuid.uuid4(),
                name="Demo Login Test Tenant",
                plan="enterprise",
                status="active",
                is_demo=True,
            )
            db.add(tenant)
            db.flush()
        else:
            tenant.is_demo = True

        user = db.query(User).filter(User.email == email).first()
        if user is None:
            user = User(
                id=uuid.uuid4(),
                email=email,
                full_name=f"{persona} demo",
                hashed_password=get_password_hash("not-used-by-demo-login"),
                role=security_role,
                is_superuser=is_superuser,
                status="active",
                email_verified=True,
                tenant_id=tenant.id,
            )
            db.add(user)
            db.flush()

        if job_role_key:
            role = (
                db.query(JobRole)
                .filter(
                    JobRole.tenant_id == tenant.id,
                    JobRole.role_key == job_role_key,
                )
                .first()
            )
            if role is None:
                role = JobRole(
                    id=uuid.uuid4(),
                    tenant_id=tenant.id,
                    role_key=job_role_key,
                    name="業務",
                    active=True,
                )
                db.add(role)
                db.flush()
            assignment = (
                db.query(UserJobRoleAssignment)
                .filter(
                    UserJobRoleAssignment.user_id == user.id,
                    UserJobRoleAssignment.job_role_id == role.id,
                )
                .first()
            )
            if assignment is None:
                db.add(
                    UserJobRoleAssignment(
                        id=uuid.uuid4(),
                        tenant_id=tenant.id,
                        user_id=user.id,
                        job_role_id=role.id,
                        is_primary=True,
                        active=True,
                    )
                )
        db.commit()
        return tenant.id
    finally:
        db.close()


@pytest.mark.asyncio
async def test_demo_login_is_disabled_by_default(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "DEMO_LOGIN_ENABLED", False)
    response = await client.post("/api/v1/auth/login/demo", json={"persona": "sales"})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_demo_login_issues_short_lived_allowlisted_token(
    client: AsyncClient, test_engine, monkeypatch: pytest.MonkeyPatch
):
    tenant_id = _seed_demo_identity(test_engine, "sales")
    monkeypatch.setattr(settings, "DEMO_LOGIN_ENABLED", True)
    monkeypatch.setattr(settings, "DEMO_TENANT_ID", str(tenant_id))
    monkeypatch.setattr(settings, "DEMO_ACCESS_TOKEN_EXPIRE_MINUTES", 60)

    response = await client.post("/api/v1/auth/login/demo", json={"persona": "sales"})
    assert response.status_code == 200
    body = response.json()
    assert body["read_only"] is False
    assert body["expires_in"] == 3600

    payload = jwt.decode(
        body["access_token"], settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
    )
    assert payload["sub"] == DEMO_PERSONAS["sales"]["email"]
    assert payload["demo_mode"] is True
    assert payload["demo_persona"] == "sales"
    assert payload["demo_read_only"] is False
    assert payload["demo_mutation_scope"] == "workflow"


@pytest.mark.asyncio
async def test_demo_viewer_token_is_explicitly_read_only(
    client: AsyncClient, test_engine, monkeypatch: pytest.MonkeyPatch
):
    tenant_id = _seed_demo_identity(test_engine, "sales")
    Session = sessionmaker(bind=test_engine)
    db = Session()
    try:
        anchor = db.query(User).filter(User.email == DEMO_PERSONAS["sales"]["email"]).one()
        viewer = User(
            id=uuid.uuid4(),
            email=DEMO_PERSONAS["viewer"]["email"],
            full_name="viewer demo",
            hashed_password=get_password_hash("not-used-by-demo-login"),
            role="viewer",
            is_superuser=False,
            status="active",
            email_verified=True,
            tenant_id=anchor.tenant_id,
        )
        db.add(viewer)
        db.commit()
    finally:
        db.close()

    monkeypatch.setattr(settings, "DEMO_LOGIN_ENABLED", True)
    monkeypatch.setattr(settings, "DEMO_TENANT_ID", str(tenant_id))
    response = await client.post("/api/v1/auth/login/demo", json={"persona": "viewer"})
    assert response.status_code == 200
    payload = jwt.decode(
        response.json()["access_token"], settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
    )
    assert response.json()["read_only"] is True
    assert payload["demo_read_only"] is True
    assert payload["demo_mutation_scope"] == "interaction"


@pytest.mark.asyncio
async def test_demo_admin_token_cannot_change_settings(
    client: AsyncClient, test_engine, monkeypatch: pytest.MonkeyPatch
):
    tenant_id = _seed_demo_identity(test_engine, "admin")
    monkeypatch.setattr(settings, "DEMO_LOGIN_ENABLED", True)
    monkeypatch.setattr(settings, "DEMO_TENANT_ID", str(tenant_id))

    login = await client.post("/api/v1/auth/login/demo", json={"persona": "admin"})
    assert login.status_code == 200
    assert login.json()["read_only"] is False
    payload = jwt.decode(
        login.json()["access_token"], settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
    )
    assert payload["demo_mutation_scope"] == "approval"

    response = await client.post(
        "/api/v1/auth/resend-verification",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "demo_scope_blocked"


@pytest.mark.asyncio
async def test_demo_admin_can_reach_decision_route_but_not_policy_mutation(
    client: AsyncClient, test_engine, monkeypatch: pytest.MonkeyPatch
):
    tenant_id = _seed_demo_identity(test_engine, "admin")
    monkeypatch.setattr(settings, "DEMO_LOGIN_ENABLED", True)
    monkeypatch.setattr(settings, "DEMO_TENANT_ID", str(tenant_id))
    login = await client.post("/api/v1/auth/login/demo", json={"persona": "admin"})
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    decision = await client.post(
        f"/api/v1/approvals/{uuid.uuid4()}/approve",
        headers=headers,
        json={"record_version": 1, "reason": "synthetic decision"},
    )
    assert decision.status_code != 403

    policy = await client.post(
        "/api/v1/approvals/policies",
        headers=headers,
        json={},
    )
    assert policy.status_code == 403
    assert policy.json()["detail"]["error"] == "demo_scope_blocked"


@pytest.mark.asyncio
async def test_demo_workflow_token_cannot_upload_or_change_settings(
    client: AsyncClient, test_engine, monkeypatch: pytest.MonkeyPatch
):
    tenant_id = _seed_demo_identity(test_engine, "sales")
    monkeypatch.setattr(settings, "DEMO_LOGIN_ENABLED", True)
    monkeypatch.setattr(settings, "DEMO_TENANT_ID", str(tenant_id))
    login = await client.post("/api/v1/auth/login/demo", json={"persona": "sales"})
    token = login.json()["access_token"]

    blocked = await client.post(
        "/api/v1/auth/resend-verification",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["error"] == "demo_scope_blocked"


def test_demo_mutation_scope_allowlist_is_fail_closed():
    from app.middleware.demo_access import demo_mutation_allowed

    assert demo_mutation_allowed("/api/v1/tasks/quote/execute", "workflow") is True
    assert demo_mutation_allowed("/api/v1/chat", "interaction") is True
    assert demo_mutation_allowed("/api/v1/forms", "interaction") is False
    assert demo_mutation_allowed("/api/v1/approvals/123/approve", "approval") is True
    assert demo_mutation_allowed("/api/v1/approvals/123/reject", "approval") is True
    assert demo_mutation_allowed("/api/v1/knowhow/123/approve", "approval") is True
    assert demo_mutation_allowed("/api/v1/approvals/policies", "approval") is False
    assert demo_mutation_allowed("/api/v1/approvals/123", "approval") is False
    assert demo_mutation_allowed("/api/v1/knowhow/123/retire", "approval") is False
    assert demo_mutation_allowed("/api/v1/forms", "approval") is False
    assert demo_mutation_allowed("/api/v1/documents/upload", "workflow") is False
    assert demo_mutation_allowed("/api/v1/connectors", "workflow") is False
    assert demo_mutation_allowed("/api/v1/admin/users", "workflow") is False
    assert demo_mutation_allowed("/api/v1/chat-evil", "workflow") is False


@pytest.mark.asyncio
async def test_demo_admin_does_not_fall_back_to_another_owner(
    client: AsyncClient, test_engine, monkeypatch: pytest.MonkeyPatch
):
    tenant_id = _seed_demo_identity(test_engine, "sales")
    Session = sessionmaker(bind=test_engine)
    db = Session()
    try:
        anchor = db.query(User).filter(User.email == DEMO_PERSONAS["sales"]["email"]).one()
        fallback = User(
            id=uuid.uuid4(),
            email="aaa-owner@demo.mka",
            full_name="Fallback demo owner",
            hashed_password=get_password_hash("not-used-by-demo-login"),
            role="owner",
            is_superuser=True,
            status="active",
            email_verified=True,
            tenant_id=anchor.tenant_id,
        )
        db.add(fallback)
        db.commit()
    finally:
        db.close()

    monkeypatch.setattr(settings, "DEMO_LOGIN_ENABLED", True)
    monkeypatch.setattr(settings, "DEMO_TENANT_ID", str(tenant_id))
    monkeypatch.setattr(settings, "DEMO_ADMIN_EMAIL", "missing-owner@demo.invalid")
    response = await client.post("/api/v1/auth/login/demo", json={"persona": "admin"})

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_demo_login_rejects_platform_superuser_identity(
    client: AsyncClient, test_engine, monkeypatch: pytest.MonkeyPatch
):
    tenant_id = _seed_demo_identity(test_engine, "admin")
    Session = sessionmaker(bind=test_engine)
    db = Session()
    try:
        admin = db.query(User).filter(User.email == DEMO_PERSONAS["admin"]["email"]).one()
        admin.is_superuser = True
        db.commit()
    finally:
        db.close()

    monkeypatch.setattr(settings, "DEMO_LOGIN_ENABLED", True)
    monkeypatch.setattr(settings, "DEMO_TENANT_ID", str(tenant_id))
    response = await client.post("/api/v1/auth/login/demo", json={"persona": "admin"})
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_demo_login_rejects_real_or_unmarked_tenant(
    client: AsyncClient, test_engine, monkeypatch: pytest.MonkeyPatch
):
    tenant_id = _seed_demo_identity(test_engine, "sales")
    Session = sessionmaker(bind=test_engine)
    db = Session()
    try:
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).one()
        tenant.is_demo = False
        db.commit()
    finally:
        db.close()

    monkeypatch.setattr(settings, "DEMO_LOGIN_ENABLED", True)
    monkeypatch.setattr(settings, "DEMO_TENANT_ID", str(tenant_id))
    response = await client.post("/api/v1/auth/login/demo", json={"persona": "sales"})

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_demo_login_rejects_unknown_persona(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "DEMO_LOGIN_ENABLED", True)
    monkeypatch.setattr(settings, "DEMO_TENANT_ID", str(uuid.uuid4()))
    response = await client.post("/api/v1/auth/login/demo", json={"persona": "unknown"})
    assert response.status_code == 422
