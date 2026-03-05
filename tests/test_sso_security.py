"""Unit tests for SSO state and PKCE flow."""
import pytest
from fastapi import HTTPException

try:
    from app.api.v1.endpoints import sso as sso_endpoints
    from app.schemas.sso import OAuthCallbackRequest, SSOStateRequest
except ImportError:
    pytest.skip("SSO module not implemented", allow_module_level=True)

from app.config import settings


class _FakeQuery:
    def __init__(self, result):
        self._result = result

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._result


class _FakeSession:
    def __init__(self, result):
        self._result = result

    def query(self, *args, **kwargs):
        return _FakeQuery(self._result)


class _FakeSSOConfig:
    def __init__(self, tenant_id, provider):
        self.tenant_id = tenant_id
        self.provider = provider
        self.enabled = True
        self.client_id = "client-id"
        self.client_secret = "client-secret"
        self.allowed_domains = []
        self.auto_create_user = True
        self.default_role = "employee"


@pytest.mark.asyncio
async def test_state_roundtrip(monkeypatch):
    monkeypatch.setattr(settings, "SECRET_KEY", "test-secret")
    payload = {"tenant_id": "t1", "provider": "google", "exp": 9999999999}
    token = sso_endpoints._sign_state(payload)
    decoded = sso_endpoints._verify_state(token)
    assert decoded == payload


def test_state_invalid_signature(monkeypatch):
    monkeypatch.setattr(settings, "SECRET_KEY", "test-secret")
    payload = {"tenant_id": "t1", "provider": "google", "exp": 9999999999}
    token = sso_endpoints._sign_state(payload)
    tampered = token + "x"
    assert sso_endpoints._verify_state(tampered) is None


def test_state_expired(monkeypatch):
    monkeypatch.setattr(settings, "SECRET_KEY", "test-secret")
    payload = {"tenant_id": "t1", "provider": "google", "exp": 1}
    token = sso_endpoints._sign_state(payload)
    assert sso_endpoints._verify_state(token) is None


def test_create_state_requires_enabled_provider():
    db = _FakeSession(result=None)
    with pytest.raises(HTTPException) as exc:
        sso_endpoints.create_sso_state(
            SSOStateRequest(tenant_id="00000000-0000-0000-0000-000000000000", provider="google"),
            db=db,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_callback_rejects_state_mismatch(monkeypatch):
    monkeypatch.setattr(settings, "SECRET_KEY", "test-secret")

    tenant_id = "11111111-1111-1111-1111-111111111111"
    cfg = _FakeSSOConfig(tenant_id, "google")
    db = _FakeSession(result=cfg)

    bad_state = sso_endpoints._sign_state({
        "tenant_id": "22222222-2222-2222-2222-222222222222",
        "provider": "google",
        "exp": 9999999999,
    })

    body = OAuthCallbackRequest(
        code="auth-code",
        redirect_uri="http://localhost/callback",
        tenant_id=tenant_id,
        provider="google",
        state=bad_state,
        code_verifier="verifier",
    )

    with pytest.raises(HTTPException) as exc:
        await sso_endpoints.sso_callback(body, db=db)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_callback_requires_code_verifier(monkeypatch):
    monkeypatch.setattr(settings, "SECRET_KEY", "test-secret")

    tenant_id = "11111111-1111-1111-1111-111111111111"
    cfg = _FakeSSOConfig(tenant_id, "google")
    db = _FakeSession(result=cfg)

    good_state = sso_endpoints._sign_state({
        "tenant_id": tenant_id,
        "provider": "google",
        "exp": 9999999999,
    })

    body = OAuthCallbackRequest(
        code="auth-code",
        redirect_uri="http://localhost/callback",
        tenant_id=tenant_id,
        provider="google",
        state=good_state,
        code_verifier="",
    )

    with pytest.raises(HTTPException) as exc:
        await sso_endpoints.sso_callback(body, db=db)
    assert exc.value.status_code == 400
