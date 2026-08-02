from typing import Literal, Optional
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict, field_validator

# Valid role values — kept in one place so model + schema stay in sync.
UserRoleLiteral = Literal["owner", "admin", "hr", "employee", "viewer"]
UserStatusLiteral = Literal["active", "inactive", "suspended"]


def _normalize_email(v: str) -> str:
    """On-prem may use .local / internal domains — do not require public EmailStr."""
    email = (v or "").strip().lower()
    if "@" not in email or len(email) < 5:
        raise ValueError("電子郵件格式無效")
    return email


# Shared properties
class UserBase(BaseModel):
    email: Optional[str] = None
    full_name: Optional[str] = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        return _normalize_email(v)


# Properties to receive via API on creation
class UserCreate(UserBase):
    email: str
    password: str
    tenant_id: UUID
    role: UserRoleLiteral = "employee"
    department_id: Optional[UUID] = None


# Properties to receive via API on update
class UserUpdate(UserBase):
    password: Optional[str] = None
    department_id: Optional[UUID] = None
    role: Optional[UserRoleLiteral] = None


class UserInDBBase(UserBase):
    id: Optional[UUID] = None
    tenant_id: Optional[UUID] = None
    role: Optional[UserRoleLiteral] = None
    status: Optional[UserStatusLiteral] = None
    department_id: Optional[UUID] = None
    is_superuser: Optional[bool] = False

    model_config = ConfigDict(from_attributes=True)


# Additional properties to return via API
class User(UserInDBBase):
    pass


# Additional properties stored in DB
class UserInDB(UserInDBBase):
    hashed_password: str
