"""Ensure Pilot accounts on the single Demo Tenant."""
from __future__ import annotations

from uuid import uuid4

from app.core.security import get_password_hash
from app.db.session import SessionLocal
from app.models.tenant import Tenant
from app.models.user import User


def upsert(
    db,
    *,
    email: str,
    role: str,
    password: str,
    full_name: str,
    tenant_id,
    is_superuser: bool = False,
):
    u = db.query(User).filter(User.email == email).first()
    if u is None:
        u = User(
            id=uuid4(),
            email=email,
            full_name=full_name,
            role=role,
            hashed_password=get_password_hash(password),
            tenant_id=tenant_id,
            is_superuser=is_superuser,
            status="active",
        )
        db.add(u)
        print(f"created {email} role={role}")
    else:
        u.role = role
        u.hashed_password = get_password_hash(password)
        u.full_name = full_name or u.full_name
        u.status = "active"
        u.tenant_id = tenant_id
        u.is_superuser = is_superuser or bool(u.is_superuser)
        print(f"updated {email} role={role}")
    return u


def main():
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(Tenant.name == "Demo Tenant").first()
        if not tenant:
            raise SystemExit("Demo Tenant missing — run scripts/initial_data.py first")

        upsert(
            db,
            email="admin@example.com",
            role="owner",
            password="admin123",
            full_name="Admin User",
            tenant_id=tenant.id,
            is_superuser=True,
        )
        upsert(
            db,
            email="employee@example.com",
            role="employee",
            password="employee123",
            full_name="員工測試",
            tenant_id=tenant.id,
        )
        upsert(
            db,
            email="hr_test@enclave.local",
            role="hr",
            password="hr123456",
            full_name="HR 測試",
            tenant_id=tenant.id,
        )
        db.commit()
        for email in (
            "admin@example.com",
            "admin@enclave.local",
            "employee@example.com",
            "hr_test@enclave.local",
        ):
            u = db.query(User).filter(User.email == email).first()
            if u:
                print("ok", u.email, u.role, u.tenant_id)
    finally:
        db.close()


if __name__ == "__main__":
    main()
