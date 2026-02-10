import logging
import os

from app.db.session import SessionLocal
from app.crud import crud_user, crud_tenant
from app.schemas.user import UserCreate
from app.schemas.tenant import TenantCreate
from app.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def init_db() -> None:
    db = SessionLocal()

    superuser_email = settings.FIRST_SUPERUSER_EMAIL
    superuser_password = settings.FIRST_SUPERUSER_PASSWORD

    if superuser_email == "admin@example.com":
        logger.warning(
            "⚠️  Using default superuser email 'admin@example.com'. "
            "Set FIRST_SUPERUSER_EMAIL in .env for production."
        )
    if superuser_password == "admin123":
        logger.warning(
            "⚠️  Using default superuser password. "
            "Set FIRST_SUPERUSER_PASSWORD in .env for production."
        )

    # Check if tenant exists
    tenant = crud_tenant.get_by_name(db, name="Demo Tenant")
    if not tenant:
        logger.info("Creating demo tenant")
        tenant_in = TenantCreate(
            name="Demo Tenant",
            tax_id="00000000",
            contact_name="System Admin",
            contact_email=superuser_email,
            contact_phone="0900000000",
            status="active"
        )
        tenant = crud_tenant.create(db, obj_in=tenant_in)
    
    # Check if superuser exists
    user = crud_user.get_by_email(db, email=superuser_email)
    if not user:
        logger.info("Creating superuser: %s", superuser_email)
        user_in = UserCreate(
            email=superuser_email,
            password=superuser_password,
            tenant_id=tenant.id,
            role="owner",
            full_name="Admin User"
        )
        user = crud_user.create(db, obj_in=user_in)
        # Set superuser flag directly
        user.is_superuser = True
        db.commit()
        db.refresh(user)
    
    db.close()

if __name__ == "__main__":
    logger.info("Creating initial data")
    init_db()
    logger.info("Initial data created")
