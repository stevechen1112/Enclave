"""三層限流（雲端模式）單元測試。"""
from unittest.mock import MagicMock

import pytest

from app.config import settings
from app.core.security import create_access_token
from app.middleware.rate_limit import RateLimitMiddleware, _cloud_layers_enabled, _jwt_subject_and_tenant


class TestCloudLayers:
    def test_cloud_layers_production(self, monkeypatch):
        monkeypatch.setattr(settings, "APP_ENV", "production")
        assert _cloud_layers_enabled() is True

    def test_cloud_layers_development(self, monkeypatch):
        monkeypatch.setattr(settings, "APP_ENV", "development")
        assert _cloud_layers_enabled() is False


class TestJwtExtraction:
    def test_extract_from_bearer(self):
        token = create_access_token("user@example.com", tenant_id="11111111-1111-1111-1111-111111111111")
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
