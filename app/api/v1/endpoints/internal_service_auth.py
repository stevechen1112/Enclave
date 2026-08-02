"""
Internal service-auth endpoints for sidecar callbacks.

Sidecar / worker 回呼 Enclave 時必須帶短效 HMAC service token。
Edge 已剝離客戶端偽造的 X-Enclave-*；此處驗證 Gateway 重簽的 token。
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field

from app.gateway.service_auth import extract_bearer_token, verify_service_token

router = APIRouter(prefix="/internal", tags=["internal-service-auth"])


class ServiceEchoRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=500)
    audience: str = Field(default="enclave-callback")


@router.post("/service-echo")
def service_echo(
    body: ServiceEchoRequest,
    authorization: Optional[str] = Header(default=None),
    x_enclave_service_token: Optional[str] = Header(default=None, alias="X-Enclave-Service-Token"),
) -> Any:
    """
    驗證 sidecar 回呼 token。通過則回傳 echo。
    audience 預設 enclave-callback；也可接受 ragflow/pipeshub/weknora。
    """
    token = x_enclave_service_token or extract_bearer_token(authorization)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing_service_token",
        )
    allowed_audiences = {
        body.audience,
        "enclave-callback",
        "ragflow",
        "pipeshub",
        "weknora",
        "sidecar",
    }
    if not any(verify_service_token(token, aud) for aud in allowed_audiences):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_or_expired_service_token",
        )
    return {
        "status": "ok",
        "echo": body.message,
        "verified": True,
    }


@router.get("/service-ping")
def service_ping(
    authorization: Optional[str] = Header(default=None),
    x_enclave_service_token: Optional[str] = Header(default=None, alias="X-Enclave-Service-Token"),
    audience: str = "enclave-callback",
) -> Any:
    token = x_enclave_service_token or extract_bearer_token(authorization)
    if not token or not verify_service_token(token, audience):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_or_expired_service_token",
        )
    return {"status": "pong", "audience": audience}
