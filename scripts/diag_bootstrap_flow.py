"""重現 experience_bootstrap 內部 try 區塊，找出吞掉的例外。"""
import sys

from app.db.session import SessionLocal
from app.models.tenant import Tenant
from app.models.user import User
from app.demo.manifest import DEMO_PERSONAS


def main() -> None:
    email = sys.argv[1] if len(sys.argv) > 1 else str(DEMO_PERSONAS["sales"]["email"])
    db = SessionLocal()
    try:
        from app.services.job_context import build_effective_job_context
        from app.services.module_registry import get_module_registry
        from app.services.module_router import get_module_router

        u = db.query(User).filter(User.email == email).first()
        if u is None:
            raise RuntimeError(f"user_not_found:{email}")
        tenant = db.query(Tenant).filter(Tenant.id == u.tenant_id).first()
        print(
            "step1 tenant="
            f"{tenant.name if tenant else None},is_demo={bool(tenant and tenant.is_demo)}"
        )

        job_ctx = build_effective_job_context(db, u)
        print(f"step2 job_ctx active_keys={list(job_ctx.active_job_role_keys)}")

        registry = get_module_registry(db)
        available = registry.get_available_modules(
            tenant_id=u.tenant_id,
            user_roles=list(job_ctx.security_roles),
            user_department_ids=list(job_ctx.department_ids),
            job_role_keys=list(job_ctx.active_job_role_keys),
        )
        print(f"step3 available={len(available)} -> {[m.get('module_key') for m in available]}")

        interaction_caps = registry.get_interaction_capabilities(u.tenant_id)
        print(f"step4 interaction_caps ok keys={list(interaction_caps)[:3] if isinstance(interaction_caps, dict) else interaction_caps}")

        from app.core.authorization import AuthorizationContext
        authz = AuthorizationContext.from_user(u)
        module_keys = job_ctx.active_module_keys or None
        entries = get_module_router(db=db).workspace_entries(authz, module_keys)
        print(f"step5 workspace_entries={len(entries)}")
        print("ALL_OK")
    finally:
        db.close()


if __name__ == "__main__":
    main()
