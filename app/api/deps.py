from typing import Generator, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from jwt import InvalidTokenError
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config import settings
from app.crud import crud_user
from app.db.session import SessionLocal
from app.models.user import User
from app.schemas.token import TokenPayload

reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/login/access-token"
)
reusable_oauth2_optional = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/login/access-token", auto_error=False
)


def get_db() -> Generator[Session, None, None]:
    try:
        db = SessionLocal()
        yield db
    finally:
        db.close()


def get_current_user(
    request: Request = None,
    db: Session = Depends(get_db),
    token: str = Depends(reusable_oauth2),
) -> User:
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        token_data = TokenPayload(**payload)
    except (InvalidTokenError, ValidationError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )
    # CG-AUTH-SSO：MFA 局部 token（mfa_pending／mfa_enroll）不得存取任何受保護 API，
    # 這是「MFA 挑戰不可繞」的強制點；局部 token 僅 /auth/mfa/* 接受。
    if payload.get("scope"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="MFA challenge required",
        )
    # P2：JWT 必須攜帶 tenant_id；先設定 RLS，再讀取該租戶 user。
    # 不再讓一般 application role 使用跨租戶 bypass。
    from app.services.rls import apply_rls_context

    if token_data.tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    apply_rls_context(db, token_data.tenant_id)
    user = crud_user.get_by_email(db, email=token_data.sub)
    if not user or user.tenant_id != token_data.tenant_id:
        # Return 401 rather than 404 to avoid leaking whether an e-mail is registered
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if request is not None:
        request.state.current_user = user
    return user


def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


def get_current_user_optional(
    db: Session = Depends(get_db),
    token: Optional[str] = Depends(reusable_oauth2_optional),
) -> Optional[User]:
    """無 token 或 token 無效時回傳 None（供 MFA setup 等雙身分端點使用）。"""
    if not token:
        return None
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        token_data = TokenPayload(**payload)
    except (InvalidTokenError, ValidationError):
        return None
    if payload.get("scope"):
        return None
    from app.services.rls import apply_rls_context

    if token_data.tenant_id is None:
        return None
    apply_rls_context(db, token_data.tenant_id)
    user = crud_user.get_by_email(db, email=token_data.sub)
    if not user or user.tenant_id != token_data.tenant_id:
        return None
    return user


def get_current_verified_user(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """CG-AUTH-SSO：聊天端點專用——EMAIL_VERIFICATION_ENABLED 時要求 email 已驗證。

    只擋聊天（計畫驗收：「未驗證不可聊天」），不影響其他 API，
    讓用戶仍可登入後補驗證。
    """
    if settings.EMAIL_VERIFICATION_ENABLED and not current_user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "email_not_verified",
                "message": "請先完成 Email 驗證再使用問答功能",
            },
        )
    return current_user
