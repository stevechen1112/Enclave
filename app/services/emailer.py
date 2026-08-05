"""Email 發送服務（CG-AUTH-SSO email verify）。

SMTP 未設定時退化為寫 log（開發模式），並在回傳值標示 delivered=False，
讓呼叫方與測試能區分「真的寄出」與「僅記錄」。生產環境必須設定 SMTP_*。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import smtplib
import time
from email.message import EmailMessage
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

_VERIFY_TOKEN_TTL = 24 * 3600  # 驗證連結 24 小時有效


def _sign(payload: dict) -> str:
    data = json.dumps(payload, sort_keys=True).encode()
    sig = hmac.new(settings.SECRET_KEY.encode(), data, hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(data).decode() + "." + sig


def _verify_token(token: str) -> Optional[dict]:
    try:
        data_b64, sig = token.rsplit(".", 1)
        data = base64.urlsafe_b64decode(data_b64)
        expected = hmac.new(settings.SECRET_KEY.encode(), data, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(data)
        if payload.get("exp", 0) < time.time():
            return None
        if payload.get("purpose") != "email_verify":
            return None
        return payload
    except Exception:
        return None


def make_verification_token(email: str) -> str:
    return _sign({"purpose": "email_verify", "email": email, "exp": int(time.time()) + _VERIFY_TOKEN_TTL})


def parse_verification_token(token: str) -> Optional[str]:
    """驗證成功回傳 email，失敗回傳 None。"""
    payload = _verify_token(token)
    return payload.get("email") if payload else None


def send_verification_email(email: str) -> bool:
    """寄出驗證信；SMTP 未設定時寫 log 並回傳 False（開發模式）。"""
    token = make_verification_token(email)
    link = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/verify-email?token={token}"

    if not settings.SMTP_HOST:
        # 不可把含 HMAC token 的連結寫入 log——生產誤未設 SMTP 時等於洩漏驗證憑證
        logger.warning(
            "SMTP 未設定：email 驗證信無法寄送（開發模式）。收件者：%s",
            email,
        )
        return False

    msg = EmailMessage()
    msg["Subject"] = "Enclave 帳號 Email 驗證"
    msg["From"] = settings.SMTP_FROM
    msg["To"] = email
    msg.set_content(
        f"請點擊以下連結完成 Email 驗證（24 小時內有效）：\n\n{link}\n\n"
        "若您沒有申請 Enclave 帳號，請忽略本信。"
    )
    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as smtp:
            if settings.SMTP_USE_TLS:
                smtp.starttls()
            if settings.SMTP_USER:
                smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            smtp.send_message(msg)
        return True
    except Exception:
        logger.exception("寄送驗證信失敗：%s", email)
        return False
