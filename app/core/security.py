from datetime import datetime, timedelta, UTC
from typing import Any, Optional, Union

from jose import jwt
from passlib.context import CryptContext

from app.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


from datetime import datetime, timedelta, UTC
from typing import Any, Optional, Union
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
    subject: Union[str, Any],
    expires_delta: Optional[timedelta] = None,
    tenant_id: Optional[Union[UUID, str]] = None,
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
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt
