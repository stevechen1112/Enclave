"""三層限流（雲端模式）單元測試。"""

from unittest.mock import AsyncMock, MagicMock

from starlette.responses import Response

from app.config import settings
from app.core.security import create_access_token
from app.middleware.ip_whitelist import get_client_ip
from app.middleware.rate_limit import (
    RateLimitMiddleware,
    _cloud_layers_enabled,
    _jwt_subject_and_tenant,
)


class TestCloudLayers:
    def test_cloud_layers_production(self, monkeypatch):
        monkeypatch.setattr(settings, "APP_ENV", "production")
        assert _cloud_layers_enabled() is True

    def test_cloud_layers_development(self, monkeypatch):
        monkeypatch.setattr(settings, "APP_ENV", "development")
        assert _cloud_layers_enabled() is False


class TestJwtExtraction:
    def test_extract_from_bearer(self):
        token = create_access_token(
            "user@example.com", tenant_id="11111111-1111-1111-1111-111111111111"
        )
        request = MagicMock()
        request.headers = {"authorization": f"Bearer {token}"}
        sub, tenant = _jwt_subject_and_tenant(request)
        assert sub == "user@example.com"
        assert tenant == "11111111-1111-1111-1111-111111111111"

    def test_invalid_token_returns_none(self):
        request = MagicMock()
        request.headers = {"authorization": "Bearer not-a-jwt"}
        sub, tenant = _jwt_subject_and_tenant(request)
        assert sub is None and tenant is None


class TestRateLimitMiddlewareSkip:
    def test_payment_notify_skipped(self):
        mw = RateLimitMiddleware(MagicMock())
        assert mw._should_skip("/api/v1/payment/notify") is True
        assert mw._should_skip("/api/v1/sso/google/callback") is True


def _request(path: str = "/api/v1/users/me") -> MagicMock:
    request = MagicMock()
    request.url.path = path
    request.client.host = "203.0.113.8"
    request.headers = {}
    return request


async def test_normal_requests_do_not_feed_abuse_counter(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    middleware = RateLimitMiddleware(MagicMock())
    middleware.limiter = MagicMock()
    middleware.limiter.is_allowed.return_value = (True, 199, 0)

    response = await middleware.dispatch(
        _request(), AsyncMock(return_value=Response(status_code=200))
    )

    assert response.status_code == 200
    middleware.limiter.record_abuse.assert_not_called()


async def test_over_limit_requests_feed_abuse_counter(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    middleware = RateLimitMiddleware(MagicMock())
    middleware.limiter = MagicMock()
    middleware.limiter.is_allowed.return_value = (False, 0, 17)
    middleware.limiter.record_abuse.return_value = False

    response = await middleware.dispatch(
        _request(), AsyncMock(return_value=Response(status_code=200))
    )

    assert response.status_code == 429
    assert response.headers["retry-after"] == "17"
    middleware.limiter.record_abuse.assert_called_once_with("ip:203.0.113.8")


async def test_repeated_over_limit_requests_escalate_to_abuse_block(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    middleware = RateLimitMiddleware(MagicMock())
    middleware.limiter = MagicMock()
    middleware.limiter.is_allowed.return_value = (False, 0, 17)
    middleware.limiter.record_abuse.return_value = True

    response = await middleware.dispatch(
        _request(), AsyncMock(return_value=Response(status_code=200))
    )

    assert response.status_code == 429
    assert response.headers["retry-after"] == "600"
    assert b'abuse_detected' in response.body


def test_rate_limit_uses_forwarded_ip_only_from_trusted_proxy(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_TRUSTED_PROXY_IPS", "172.16.0.0/12")
    middleware = RateLimitMiddleware(MagicMock())
    request = MagicMock()
    request.client.host = "172.18.0.4"
    request.headers = {"X-Forwarded-For": "203.0.113.8, 172.18.0.4"}
    assert get_client_ip(request, middleware.trusted_proxies) == "203.0.113.8"


def test_rate_limit_ignores_client_spoofed_leftmost_forwarded_ip(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_TRUSTED_PROXY_IPS", "172.16.0.0/12")
    middleware = RateLimitMiddleware(MagicMock())
    request = MagicMock()
    request.client.host = "172.18.0.4"
    request.headers = {
        "X-Forwarded-For": "198.51.100.99, 203.0.113.8, 172.18.0.3"
    }
    assert get_client_ip(request, middleware.trusted_proxies) == "203.0.113.8"


def test_rate_limit_fails_safe_on_invalid_forwarded_chain(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_TRUSTED_PROXY_IPS", "172.16.0.0/12")
    middleware = RateLimitMiddleware(MagicMock())
    request = MagicMock()
    request.client.host = "172.18.0.4"
    request.headers = {"X-Forwarded-For": "spoofed, 203.0.113.8"}
    assert get_client_ip(request, middleware.trusted_proxies) == "172.18.0.4"


def test_gateway_general_api_does_not_duplicate_application_rate_limit():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for filename in ("gateway.conf", "gateway-ssl.conf"):
        config = (root / "nginx" / filename).read_text(encoding="utf-8")
        assert "limit_req zone=api_general" not in config
        assert "zone=api_auth:5m    rate=30r/m" in config
        assert "limit_req zone=api_auth burst=10 nodelay" in config
        assert "limit_req_status 429" in config
