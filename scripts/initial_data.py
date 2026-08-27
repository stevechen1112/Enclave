import logging

from app.config import settings
from app.crud import crud_tenant, crud_user
from app.db.session import MaintenanceSessionLocal
from app.schemas.tenant import TenantCreate
from app.schemas.user import UserCreate
from app.services.rls import apply_rls_bypass

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def init_db() -> None:
    superuser_email = settings.FIRST_SUPERUSER_EMAIL
    superuser_password = settings.FIRST_SUPERUSER_PASSWORD

    if superuser_email == "admin@example.com":
        logger.warning(
            "⚠️  Using default superuser email 'admin@example.com'. "
            "Set FIRST_SUPERUSER_EMAIL in .env for production."
        )
    if len(superuser_password) < 16:
        raise RuntimeError(
            "FIRST_SUPERUSER_PASSWORD must be an injected high-entropy value "
            "with at least 16 characters."
        )

    # Bootstrap is a platform-wide operation: an ordinary application login is
    # intentionally unable to discover or create tenants under FORCE RLS.
    # Use the dedicated maintenance identity and record the bypass before any
    # cross-tenant lookup or write.
    db = MaintenanceSessionLocal()
    try:
        organization_name = settings.ORGANIZATION_NAME.strip() or "My Organization"
        apply_rls_bypass(
            db,
            actor_identity=f"bootstrap:{superuser_email}",
            operation="initialize_superuser",
            reason="Idempotent deployment bootstrap for the configured organization",
            metadata={"organization_name": organization_name},
        )

        # Initial administrator belongs to the configured real organization.
        # The passwordless public Demo is created separately.
        tenant = crud_tenant.get_by_name(db, name=organization_name)
        if not tenant:
            logger.info("Creating organization tenant: %s", organization_name)
            tenant_in = TenantCreate(
                name=organization_name,
                plan="enterprise",
                status="active",
            )
            tenant = crud_tenant.create(db, obj_in=tenant_in)

        user = crud_user.get_by_email(db, email=superuser_email)
        if not user:
            logger.info("Creating superuser: %s", superuser_email)
            user_in = UserCreate(
                email=superuser_email,
                password=superuser_password,
                tenant_id=tenant.id,
                role="owner",
                full_name="Admin User",
            )
            user = crud_user.create(db, obj_in=user_in)
            user.is_superuser = True
            db.commit()
            db.refresh(user)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    logger.info("Creating initial data")
    init_db()
    logger.info("Initial data created")
