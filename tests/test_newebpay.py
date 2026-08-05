"""CG-PAY NewebPay 單元測試。"""
import json
import urllib.parse
from unittest.mock import patch

import pytest

from app.services.newebpay import (
    NewebPayProvider,
    _aes_decrypt,
    _aes_encrypt,
    _parse_trade_info,
    _sha256_hash,
)
from app.services.payment_provider import CheckoutRequest


class TestParseTradeInfo:
    def test_json_format(self):
        payload = {
            "Status": "SUCCESS",
            "Result": {"MerchantOrderNo": "ENC1001", "Amt": 990, "TradeNo": "GW12345"},
        }
        result = _parse_trade_info(json.dumps(payload))
        assert result["Status"] == "SUCCESS"
        assert result["Result"]["MerchantOrderNo"] == "ENC1001"

    def test_url_encoded_with_json_result(self):
        inner = json.dumps({"MerchantOrderNo": "ENC2002", "Amt": 1500, "TradeNo": "GW67890"})
        body = urllib.parse.urlencode({"Status": "SUCCESS", "Result": inner})
        result = _parse_trade_info(body)
        assert result["Result"]["MerchantOrderNo"] == "ENC2002"


class TestAESRoundTrip:
    KEY = "abcdefghijklmnopqrstuvwxyz123456"
    IV = "abcdefghijklmnop"

    def test_round_trip(self):
        data = "MerchantOrderNo=ENC123&Amt=990"
        encrypted = _aes_encrypt(data, self.KEY, self.IV)
        assert _aes_decrypt(encrypted, self.KEY, self.IV) == data

    def test_sha256_uppercase(self):
        encrypted = _aes_encrypt("test", self.KEY, self.IV)
        h = _sha256_hash(encrypted, self.KEY, self.IV)
        assert h == h.upper()


class TestTradeNoUniqueness:
    @patch("app.services.newebpay.settings")
    def test_no_collision(self, mock_settings):
        mock_settings.NEWEBPAY_MERCHANT_ID = "TEST_MID"
        mock_settings.NEWEBPAY_HASH_KEY = "a" * 32
        mock_settings.NEWEBPAY_HASH_IV = "b" * 16
        mock_settings.NEWEBPAY_TEST_MODE = True
        mock_settings.BACKEND_BASE_URL = "http://localhost:8000"
        mock_settings.FRONTEND_BASE_URL = "http://localhost:3000"

        provider = NewebPayProvider()
        req = CheckoutRequest(tenant_id="t-001", plan="team", amount=2990, email="a@b.com")
        trade_nos = {provider.create_checkout(req).trade_no for _ in range(50)}
        assert len(trade_nos) == 50

    @patch("app.services.newebpay.settings")
    def test_trade_no_prefix(self, mock_settings):
        mock_settings.NEWEBPAY_MERCHANT_ID = "TEST_MID"
        mock_settings.NEWEBPAY_HASH_KEY = "a" * 32
        mock_settings.NEWEBPAY_HASH_IV = "b" * 16
        mock_settings.NEWEBPAY_TEST_MODE = True
        mock_settings.BACKEND_BASE_URL = "http://localhost:8000"
        mock_settings.FRONTEND_BASE_URL = "http://localhost:3000"

        trade_no = NewebPayProvider().create_checkout(
            CheckoutRequest(tenant_id="t", plan="team", amount=100, email="x@y.com")
        ).trade_no
        assert trade_no.startswith("ENC")
        assert len(trade_no) == 24


class TestVerifyWebhook:
    KEY = "abcdefghijklmnopqrstuvwxyz123456"
    IV = "abcdefghijklmnop"

    @patch("app.services.newebpay.settings")
    def test_success_webhook(self, mock_settings):
        mock_settings.NEWEBPAY_MERCHANT_ID = "TEST_MID"
        mock_settings.NEWEBPAY_HASH_KEY = self.KEY
        mock_settings.NEWEBPAY_HASH_IV = self.IV

        inner = {
            "Status": "SUCCESS",
            "Result": {
                "MerchantOrderNo": "ENC1234567890",
                "TradeNo": "GW0001",
                "Amt": 2990,
                "OrderComment": json.dumps({"tenant_id": "t-abc", "plan": "team"}),
            },
        }
        plaintext = json.dumps(inner)
        encrypted = _aes_encrypt(plaintext, self.KEY, self.IV)
        sha = _sha256_hash(encrypted, self.KEY, self.IV)

        event = NewebPayProvider().verify_webhook(
            {"Status": "SUCCESS", "TradeInfo": encrypted, "TradeSha": sha}
        )
        assert event.event_type == "payment.success"
        assert event.plan == "team"
        assert event.amount == 2990

    @patch("app.services.newebpay.settings")
    def test_bad_sha_raises(self, mock_settings):
        mock_settings.NEWEBPAY_MERCHANT_ID = "TEST_MID"
        mock_settings.NEWEBPAY_HASH_KEY = self.KEY
        mock_settings.NEWEBPAY_HASH_IV = self.IV

        encrypted = _aes_encrypt('{"Status":"SUCCESS"}', self.KEY, self.IV)
        with pytest.raises(ValueError, match="TradeSha verification failed"):
            NewebPayProvider().verify_webhook(
                {"Status": "SUCCESS", "TradeInfo": encrypted, "TradeSha": "BAD"}
            )
