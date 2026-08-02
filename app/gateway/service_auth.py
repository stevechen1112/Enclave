"""
Shared auth headers for sidecar HTTP adapters.

支援：
  - 靜態 API key（下游原生 Bearer）
  - 短效簽章 service token（HMAC，可輪替）
  - 可選 mTLS client cert 路徑設定（httpx 使用）
"""
from __future__ import annotations

import hashlib
import hmac
import time
from typing import Dict, Optional, Tuple

from app.config import settings


def mint_service_token(
    audience: str,
    ttl_seconds: Optional[int] = None,
    subject: str = "enclave-gateway",
) -> str:
    """
    產生短效 service token。

    格式：v1.{audience}.{subject}.{exp}.{sig}
    sig = HMAC-SHA256(SECRET_KEY, payload)
    """
    ttl = ttl_seconds if ttl_seconds is not None else int(
        getattr(settings, "SERVICE_TOKEN_TTL_SECONDS", 300)
    )
    exp = int(time.time()) + max(30, ttl)
    payload = f"v1|{audience}|{subject}|{exp}"
    secret = (settings.SECRET_KEY or "dev").encode("utf-8")
    sig = hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"v1.{audience}.{subject}.{exp}.{sig}"


def verify_service_token(token: str, expected_audience: str) -> bool:
    """驗證短效 service token（用於內部 endpoint 或 sidecar 回呼）。"""
    try:
        parts = token.split(".")
        if len(parts) != 5 or parts[0] != "v1":
            return False
        _, audience, subject, exp_s, sig = parts
        if audience != expected_audience:
            return False
        exp = int(exp_s)
        if exp < int(time.time()):
            return False
        payload = f"v1|{audience}|{subject}|{exp}"
        secret = (settings.SECRET_KEY or "dev").encode("utf-8")
        expected = hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, sig)
    except Exception:
        return False


def extract_bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


def build_auth_headers(api_key: Optional[str] = None, audience: str = "sidecar") -> Dict[str, str]:
    """
    Auth headers only（multipart 上傳不可帶 Content-Type: application/json）。

    規則：
      - 若有下游原生 API key → Authorization=Bearer <api_key>
      - 一律附帶短效 X-Enclave-Service-Token（供 Enclave 回呼驗證與稽核）
    """
    headers: Dict[str, str] = {}
    token = mint_service_token(audience=audience)
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    else:
        headers["Authorization"] = f"Bearer {token}"
    headers["X-Enclave-Service-Token"] = token
    headers["X-Enclave-Caller"] = "gateway"
    headers["X-Enclave-Audience"] = audience
    return headers


def build_service_headers(api_key: Optional[str] = None, audience: str = "sidecar") -> Dict[str, str]:
    headers = build_auth_headers(api_key=api_key, audience=audience)
    headers["Content-Type"] = "application/json"
    return headers


def mtls_client_cert() -> Optional[Tuple[str, str]]:
    """
    回傳 (cert_path, key_path) 供 httpx.AsyncClient(cert=...) 使用。
    未設定時回傳 None（開發環境可僅用短效 token）。
    """
    cert = getattr(settings, "MTLS_CLIENT_CERT", "") or ""
    key = getattr(settings, "MTLS_CLIENT_KEY", "") or ""
    if cert and key:
        return (cert, key)
    return None


def make_httpx_client(timeout: float = 30.0):
    """建立帶可選 mTLS 的 AsyncClient。"""
    import httpx
    kwargs: Dict[str, object] = {"timeout": timeout}
    cert = mtls_client_cert()
    if cert:
        kwargs["cert"] = cert
    ca = getattr(settings, "MTLS_CA_CERT", "") or ""
    if ca:
        kwargs["verify"] = ca
    return httpx.AsyncClient(**kwargs)
