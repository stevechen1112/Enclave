from app.db.session import SessionLocal
from app.crud import crud_user, crud_tenant
from app.schemas.user import UserCreate
from app.schemas.tenant import TenantCreate

EMAIL = "hr@test.com"
PASSWORD = "hr123456"
FULL_NAME = "HR User"
ROLE = "admin"

db = SessionLocal()

tenant = crud_tenant.get_by_name(db, name="Demo Tenant")
if not tenant:
    tenant_in = TenantCreate(
        name="Demo Tenant",
        tax_id="00000000",
        contact_name="System Admin",
        contact_email="admin@example.com",
        contact_phone="0900000000",
        status="active",
    )
    tenant = crud_tenant.create(db, obj_in=tenant_in)

user = crud_user.get_by_email(db, email=EMAIL)
created = False
if not user:
    user_in = UserCreate(
        email=EMAIL,
        password=PASSWORD,
        tenant_id=tenant.id,
        role=ROLE,
        full_name=FULL_NAME,
    )
    crud_user.create(db, obj_in=user_in)
    created = True

db.close()
print("HR user created" if created else "HR user already exists")
