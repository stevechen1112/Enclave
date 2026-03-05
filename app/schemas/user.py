from typing import Literal, Optional
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field, ConfigDict

# Valid role values — kept in one place so model + schema stay in sync.
UserRoleLiteral = Literal["owner", "admin", "hr", "employee", "viewer"]
UserStatusLiteral = Literal["active", "inactive", "suspended"]


# Shared properties
class UserBase(BaseModel):
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None


# Properties to receive via API on creation
class UserCreate(UserBase):
    email: EmailStr
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
