"""TOTP（RFC 6238）— CG-AUTH-SSO owner MFA。

刻意只用標準庫（hmac/hashlib/base64），不引入 pyotp 依賴：
演算法本身約 30 行，且可完全離線測試，減少供應鏈面。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time

_PERIOD = 30  # seconds
_DIGITS = 6
_WINDOW = 1  # 允許前後各一個時間窗（時鐘偏移容忍）


def generate_secret() -> str:
    """產生 base32 編碼的 TOTP secret（160 bits）。"""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _decode_secret(secret: str) -> bytes:
    pad = "=" * (-len(secret) % 8)
    return base64.b32decode((secret + pad).upper())


def _hotp(secret_bytes: bytes, counter: int) -> str:
    msg = struct.pack(">Q", counter)
    digest = hmac.new(secret_bytes, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % (10 ** _DIGITS)
    return str(code).zfill(_DIGITS)


def totp_at(secret: str, timestamp: float) -> str:
    """計算指定時間點的 TOTP 碼（測試用）。"""
    return _hotp(_decode_secret(secret), int(timestamp // _PERIOD))


def verify(secret: str, code: str, *, at: float | None = None) -> bool:
    """驗證 TOTP 碼，容忍 ±1 時間窗。比對使用 constant-time。"""
    if not secret or not code:
        return False
    code = code.strip().replace(" ", "")
    if not code.isdigit():
        return False
    now = time.time() if at is None else at
    counter = int(now // _PERIOD)
    secret_bytes = _decode_secret(secret)
    for drift in (-_WINDOW, 0, _WINDOW):
        if hmac.compare_digest(_hotp(secret_bytes, counter + drift), code):
            return True
    return False


def provisioning_uri(secret: str, *, email: str, issuer: str = "Enclave") -> str:
    """產生 otpauth:// URI 供 Authenticator App 掃描。"""
    from urllib.parse import quote

    return (
        f"otpauth://totp/{quote(issuer)}:{quote(email)}"
        f"?secret={secret}&issuer={quote(issuer)}&digits={_DIGITS}&period={_PERIOD}"
    )
