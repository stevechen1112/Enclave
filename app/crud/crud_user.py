import secrets
from typing import Optional

from sqlalchemy.orm import Session

from app.core.security import get_password_hash, verify_password
from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate


def get_by_email(db: Session, *, email: str) -> Optional[User]:
    return db.query(User).filter(User.email == email).first()


def create(db: Session, *, obj_in: UserCreate) -> User:
    db_obj = User(
        email=obj_in.email,
        hashed_password=get_password_hash(obj_in.password),
        full_name=obj_in.full_name,
        tenant_id=obj_in.tenant_id,
        role=obj_in.role if hasattr(obj_in, 'role') else "employee",
        status="active",
    )
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj


def authenticate(
    db: Session, *, email: str, password: str
) -> Optional[User]:
    user = get_by_email(db, email=email)
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def create_sso_user(
    db: Session, *, email: str, tenant_id, role: str = "employee"
) -> User:
    """SSO 自動開戶（僅在 tenant SSO config auto_create_user=True 時被呼叫）。

    IdP 已驗證 email，故 email_verified=True；密碼設為不可用雜湊，
    此帳號只能走 SSO 登入（避免平行密碼登入面）。
    """
    db_obj = User(
        email=email,
        hashed_password=get_password_hash(secrets.token_urlsafe(32)),
        full_name=email.split("@")[0],
        tenant_id=tenant_id,
        role=role,
        status="active",
        email_verified=True,
    )
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj
