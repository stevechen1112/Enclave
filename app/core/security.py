from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from jose import jwt
from passlib.context import CryptContext

from app.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(
    subject: Any,
    expires_delta: timedelta | None = None,
    tenant_id: UUID | str | None = None,
    additional_claims: dict[str, Any] | None = None,
) -> str:
    """Create a signed JWT.

    Args:
        subject:      The user identifier embedded in ``sub`` (typically email).
        expires_delta: Override the default expiry from settings.
        tenant_id:    Optional tenant UUID embedded so middleware can read it
                      without an extra DB roundtrip.
    """
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )
    to_encode: dict[str, Any] = {"exp": expire, "sub": str(subject)}
    if tenant_id is not None:
        to_encode["tenant_id"] = str(tenant_id)
    if additional_claims:
        reserved = {"exp", "sub", "tenant_id"}.intersection(additional_claims)
        if reserved:
            raise ValueError(f"additional claims contain reserved keys: {sorted(reserved)}")
        to_encode.update(additional_claims)
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


# CG-AUTH-SSO：MFA 局部 token 的 scope 值
SCOPE_MFA_PENDING = "mfa_pending"  # 已過密碼、待 TOTP 挑戰
SCOPE_MFA_ENROLL = "mfa_enroll"    # 強制開通流程中、僅可呼叫 MFA setup


def create_partial_token(
    subject: Any,
    *,
    scope: str,
    tenant_id: UUID | str | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    """MFA 局部 token：帶 scope claim，get_current_user 一律拒絕（不可繞過挑戰）。

    只有 /auth/mfa/* 端點透過 decode_partial_token 接受此類 token。
    """
    if scope not in (SCOPE_MFA_PENDING, SCOPE_MFA_ENROLL):
        raise ValueError(f"invalid partial token scope: {scope}")
    expire = datetime.now(UTC) + (
        expires_delta or timedelta(minutes=settings.MFA_PARTIAL_TOKEN_MINUTES)
    )
    to_encode: dict[str, Any] = {"exp": expire, "sub": str(subject), "scope": scope}
    if tenant_id is not None:
        to_encode["tenant_id"] = str(tenant_id)
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_partial_token(
    token: str, *, expected_scope: str | None = None
) -> dict[str, Any] | None:
    """解碼並驗證局部 token；scope 不符或驗證失敗回傳 None。"""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except jwt.JWTError:
        return None
    scope = payload.get("scope")
    if scope not in (SCOPE_MFA_PENDING, SCOPE_MFA_ENROLL):
        return None
    if expected_scope is not None and scope != expected_scope:
        return None
    return payload
