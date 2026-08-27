"""NewebPay (藍新金流) — CG-PAY，移植自 UniHR 實戰路徑。"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.parse
import uuid
from binascii import hexlify, unhexlify

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app.config import settings
from app.services.payment_provider import (
    CheckoutRequest,
    CheckoutResult,
    PaymentProvider,
    WebhookEvent,
)

logger = logging.getLogger("enclave.newebpay")

NEWEBPAY_MPG_URL = "https://core.newebpay.com/MPG/mpg_gateway"
NEWEBPAY_MPG_URL_TEST = "https://ccore.newebpay.com/MPG/mpg_gateway"


def _get_mpg_url() -> str:
    if settings.NEWEBPAY_TEST_MODE:
        return NEWEBPAY_MPG_URL_TEST
    return NEWEBPAY_MPG_URL


def _aes_encrypt(data: str, key: str, iv: str) -> str:
    padder = padding.PKCS7(algorithms.AES.block_size).padder()
    padded = padder.update(data.encode("utf-8")) + padder.finalize()
    encryptor = Cipher(
        algorithms.AES(key.encode("utf-8")), modes.CBC(iv.encode("utf-8"))
    ).encryptor()
    encrypted = encryptor.update(padded) + encryptor.finalize()
    return hexlify(encrypted).decode("utf-8")


def _aes_decrypt(hex_data: str, key: str, iv: str) -> str:
    decryptor = Cipher(
        algorithms.AES(key.encode("utf-8")), modes.CBC(iv.encode("utf-8"))
    ).decryptor()
    padded = decryptor.update(unhexlify(hex_data)) + decryptor.finalize()
    unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
    decrypted = unpadder.update(padded) + unpadder.finalize()
    return decrypted.decode("utf-8")


def _sha256_hash(trade_info_encrypted: str, key: str, iv: str) -> str:
    raw = f"HashKey={key}&{trade_info_encrypted}&HashIV={iv}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest().upper()


def _parse_trade_info(decrypted_str: str) -> dict:
    stripped = decrypted_str.strip()
    if stripped.startswith("{"):
        return json.loads(stripped)

    parsed = urllib.parse.parse_qs(stripped, keep_blank_values=True)
    trade_info = {
        key: values[0] if len(values) == 1 else values for key, values in parsed.items()
    }
    result_payload = trade_info.get("Result")
    if isinstance(result_payload, str) and result_payload:
        try:
            trade_info["Result"] = json.loads(result_payload)
        except json.JSONDecodeError:
            pass
    return trade_info


class NewebPayProvider(PaymentProvider):
    def __init__(self):
        self.merchant_id = settings.NEWEBPAY_MERCHANT_ID
        self.hash_key = settings.NEWEBPAY_HASH_KEY
        self.hash_iv = settings.NEWEBPAY_HASH_IV

    def create_checkout(self, req: CheckoutRequest) -> CheckoutResult:
        trade_no = f"ENC{int(time.time() * 1000)}{uuid.uuid4().hex[:8].upper()}"
        backend = settings.BACKEND_BASE_URL.rstrip("/")
        frontend = settings.FRONTEND_BASE_URL.rstrip("/")

        trade_info = {
            "MerchantID": self.merchant_id,
            "RespondType": "JSON",
            "TimeStamp": str(int(time.time())),
            "Version": "2.0",
            "MerchantOrderNo": trade_no,
            "Amt": req.amount,
            "ItemDesc": req.description or f"Enclave {req.plan} 方案",
            "Email": req.email,
            "NotifyURL": f"{backend}/api/v1/payment/notify",
            "ReturnURL": f"{frontend}/subscription?payment=complete",
            "ClientBackURL": f"{frontend}/subscription",
            "CREDIT": 1,
            "VACC": 0,
            "CVS": 0,
            "OrderComment": json.dumps({"tenant_id": req.tenant_id, "plan": req.plan}),
        }

        trade_info_str = urllib.parse.urlencode(trade_info)
        trade_info_encrypted = _aes_encrypt(trade_info_str, self.hash_key, self.hash_iv)
        trade_sha = _sha256_hash(trade_info_encrypted, self.hash_key, self.hash_iv)

        return CheckoutResult(
            checkout_url=_get_mpg_url(),
            trade_no=trade_no,
            form_fields={
                "MerchantID": self.merchant_id,
                "TradeInfo": trade_info_encrypted,
                "TradeSha": trade_sha,
                "Version": "2.0",
            },
        )

    def verify_webhook(self, form_data: dict) -> WebhookEvent:
        status_code = form_data.get("Status")
        trade_info_encrypted = form_data.get("TradeInfo", "")
        trade_sha = form_data.get("TradeSha", "")

        if not trade_info_encrypted or not trade_sha:
            raise ValueError("Missing TradeInfo or TradeSha")

        expected_sha = _sha256_hash(trade_info_encrypted, self.hash_key, self.hash_iv)
        if trade_sha.upper() != expected_sha:
            raise ValueError("TradeSha verification failed")

        decrypted_str = _aes_decrypt(trade_info_encrypted, self.hash_key, self.hash_iv)
        trade_info = _parse_trade_info(decrypted_str)

        result = trade_info.get("Result", trade_info)
        merchant_order_no = result.get("MerchantOrderNo", "")
        gateway_trade_no = result.get("TradeNo", "")
        amount = int(result.get("Amt", 0))

        order_comment = result.get("OrderComment", "{}")
        try:
            comment_data = json.loads(order_comment)
        except (json.JSONDecodeError, TypeError):
            comment_data = {}

        trade_status = trade_info.get("Status") or status_code
        event_type = (
            "payment.success" if trade_status == "SUCCESS" else "payment.failed"
        )

        logger.info(
            "NewebPay notify: type=%s trade_no=%s tenant=%s",
            event_type,
            merchant_order_no,
            comment_data.get("tenant_id"),
        )

        return WebhookEvent(
            event_type=event_type,
            trade_no=merchant_order_no,
            gateway_trade_no=gateway_trade_no,
            amount=amount,
            currency="TWD",
            tenant_id=str(comment_data.get("tenant_id", "")),
            plan=str(comment_data.get("plan", "")),
            raw=trade_info,
        )


def get_payment_provider() -> NewebPayProvider:
    return NewebPayProvider()
