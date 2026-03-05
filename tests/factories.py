"""
測試用資料工廠
提供 Tenant、User、Document 的快速建立函式。
所有工廠函式直接操作 SQLAlchemy session，與真實 DB 互動，無任何 mock。
"""
from __future__ import annotations

import uuid
from typing import Optional
from sqlalchemy.orm import Session

from app.core.security import get_password_hash
from app.models.tenant import Tenant
from app.models.user import User
from app.models.document import Document


# ── Tenant ────────────────────────────────────────────

def make_tenant(
    db: Session,
    *,
    name: str = "Test Company",
    plan: str = "free",
    status: str = "active",
    **kwargs,
) -> Tenant:
    """建立並 commit 一個 Tenant，回傳 ORM 物件。"""
    t = Tenant(
        id=uuid.uuid4(),
        name=name,
        plan=plan,
        status=status,
        **kwargs,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


# ── User ──────────────────────────────────────────────

def make_user(
    db: Session,
    *,
    tenant: Tenant,
    email: Optional[str] = None,
    password: str = "Test1234!",
    full_name: str = "Test User",
    role: str = "employee",
    is_superuser: bool = False,
    status: str = "active",
) -> User:
    """建立並 commit 一個 User，回傳 ORM 物件。"""
    if email is None:
        email = f"user-{uuid.uuid4().hex[:8]}@example.com"
    u = User(
        id=uuid.uuid4(),
        email=email,
        full_name=full_name,
        hashed_password=get_password_hash(password),
        role=role,
        is_superuser=is_superuser,
        status=status,
        tenant_id=tenant.id,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


# ── Document ──────────────────────────────────────────

def make_document(
    db: Session,
    *,
    tenant: Tenant,
    uploader: Optional[User] = None,
    filename: str = "sample.txt",
    file_type: str = "txt",
    status: str = "completed",
    source_type: str = "file",
) -> Document:
    """建立並 commit 一個 Document（不含 chunks），回傳 ORM 物件。"""
    d = Document(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        uploaded_by=uploader.id if uploader else None,
        filename=filename,
        file_type=file_type,
        file_path=f"./test-uploads/{filename}",
        file_size=1024,
        source_type=source_type,
        status=status,
    )
    db.add(d)
    db.commit()
    db.refresh(d)
    return d
