"""Bugbot code review 修補回歸測試（2026-08-05）。"""
import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from app.api.v1.endpoints.payment import PaymentNotifyError, _handle_payment_success
from app.config import settings
from app.crud import crud_tenant
from app.db.base_class import Base
from app.models.tenant import Tenant
from app.models.user import User
from app.services.payment_provider import WebhookEvent


@pytest.fixture
def db_session(test_engine):
    import app.models  # noqa: F401
    Base.metadata.create_all(bind=test_engine)
    Session = sessionmaker(bind=test_engine)
    db = Session()
    yield db
    db.close()


class TestTokenReserveEstimate:
    def test_reserve_counts_estimated_tokens(self, db_session, monkeypatch):
        monkeypatch.setattr(settings, "CHAT_TOKEN_RESERVE_ESTIMATE", 5000)
        tenant = Tenant(
            name=f"T-{uuid.uuid4().hex[:6]}",
            plan="free",
            monthly_token_limit=8000,
            monthly_query_limit=100,
        )
        db_session.add(tenant)
        db_session.commit()
        db_session.refresh(tenant)

        user = User(
            email=f"u-{uuid.uuid4().hex[:8]}@test.com",
            hashed_password="x",
            tenant_id=tenant.id,
            role="owner",
            status="active",
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        r1 = crud_tenant.reserve_chat_quota(db_session, tenant.id, user.id)
        assert r1["allowed"] is True

        r2 = crud_tenant.reserve_chat_quota(db_session, tenant.id, user.id)
        assert r2["allowed"] is False
        assert r2.get("axis") == "token"


class TestPaymentWebhookAtomic:
    def test_success_single_commit(self, db_session):
        tenant = Tenant(name="PayT", plan="pilot")
        db_session.add(tenant)
        db_session.commit()
        db_session.refresh(tenant)

        trade_id = f"GW-{uuid.uuid4().hex[:8]}"
        event = WebhookEvent(
            event_type="payment.success",
            trade_no=f"ENC-{uuid.uuid4().hex[:8]}",
            gateway_trade_no=trade_id,
            amount=2990,
            currency="TWD",
            tenant_id=str(tenant.id),
            plan="team",
            raw={},
        )
        _handle_payment_success(db_session, event)

        db_session.refresh(tenant)
        assert tenant.plan == "team"
        from app.models.billing import BillingRecord

        rec = db_session.query(BillingRecord).filter(BillingRecord.external_id == trade_id).first()
        assert rec is not None
        assert rec.status == "paid"

    def test_missing_tenant_raises(self, db_session):
        event = WebhookEvent(
            event_type="payment.success",
            trade_no="ENC999",
            gateway_trade_no="GW9",
            amount=100,
            currency="TWD",
            tenant_id=str(uuid.uuid4()),
            plan="team",
            raw={},
        )
        with pytest.raises(PaymentNotifyError):
            _handle_payment_success(db_session, event)


@pytest.mark.asyncio
async def test_chat_404_does_not_consume_query_quota(client, superuser_headers, monkeypatch):
    """對話不存在時不應消耗查詢配額。"""
    from tests.conftest import create_tenant, create_user, login_user

    monkeypatch.setattr(settings, "CHAT_TOKEN_RESERVE_ESTIMATE", 100)

    t = await create_tenant(client, superuser_headers, {
        "name": "NoConv", "tax_id": "NC01",
        "contact_name": "C", "contact_email": "c@nc01.com",
        "contact_phone": "0900000001", "plan": "team",
    })
    await create_user(client, superuser_headers, {
        "email": "owner@nc01.com", "password": "Owner123!",
        "full_name": "Owner", "role": "owner", "tenant_id": t["id"],
    })
    h = await login_user(client, "owner@nc01.com", "Owner123!")

    await client.put(
        f"/api/v1/admin/tenants/{t['id']}/quota",
        headers=superuser_headers,
        json={"monthly_query_limit": 1, "monthly_token_limit": 1_000_000},
    )

    bad_id = str(uuid.uuid4())
    r = await client.post(
        "/api/v1/chat/chat",
        headers=h,
        json={"question": "test", "conversation_id": bad_id},
    )
    assert r.status_code == 404

    r2 = await client.post(
        "/api/v1/chat/chat",
        headers=h,
        json={"question": "ok question"},
    )
    assert r2.status_code != 429


@pytest.mark.asyncio
async def test_sso_redirect_uri_mismatch(client, superuser_headers, monkeypatch):
    from tests.test_auth_hardening import TestSsoLogin

    t, _, _domain = await TestSsoLogin()._make_sso_tenant(
        client, superuser_headers, monkeypatch, tax_id="RD01", name="Redirect"
    )
    st = await client.post("/api/v1/sso/state", json={"tenant_id": t["id"], "provider": "google"})
    cb = await client.post(
        "/api/v1/sso/callback",
        json={
            "code": "authcode",
            "redirect_uri": "http://evil.com/cb",
            "tenant_id": t["id"],
            "provider": "google",
            "state": st.json()["state"],
            "code_verifier": "verifier",
        },
    )
    assert cb.status_code == 400
    assert "sso_redirect_uri_mismatch" in str(cb.json())
