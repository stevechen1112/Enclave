"""重現 experience_bootstrap 內部 try 區塊，找出吞掉的例外。"""
import sys
import traceback

from app.db.session import SessionLocal
from app.models.tenant import Tenant
from app.models.user import User


def main() -> None:
    email = sys.argv[1] if len(sys.argv) > 1 else "sales@demo.mka"
    db = SessionLocal()
    try:
        from app.services.job_context import build_effective_job_context
        from app.services.mka_module_seed import (
            ensure_tenant_module_bindings,
            seed_canonical_modules,
            seed_canonical_task_definitions,
            seed_default_job_roles,
        )
        from app.services.module_registry import get_module_registry
        from app.services.module_router import get_module_router

        u = db.query(User).filter(User.email == email).first()
        print("step1 seed_canonical_modules")
        seed_canonical_modules(db)
        print("step2 seed_canonical_task_definitions")
        seed_canonical_task_definitions(db)
        tenant = db.query(Tenant).filter(Tenant.id == u.tenant_id).first()
        print(f"step3 tenant={tenant.name if tenant else None}")
        if tenant is not None and tenant.name == "Demo Tenant":
            ensure_tenant_module_bindings(db, u.tenant_id)
        print("step4 seed_default_job_roles")
        seed_default_job_roles(db, u.tenant_id)
        db.commit()
        print("step5 commit ok")

        job_ctx = build_effective_job_context(db, u)
        print(f"step6 job_ctx active_keys={list(job_ctx.active_job_role_keys)}")

        registry = get_module_registry(db)
        available = registry.get_available_modules(
            tenant_id=u.tenant_id,
            user_roles=list(job_ctx.security_roles),
            user_department_ids=list(job_ctx.department_ids),
            job_role_keys=list(job_ctx.active_job_role_keys),
        )
        print(f"step7 available={len(available)} -> {[m.get('module_key') for m in available]}")

        interaction_caps = registry.get_interaction_capabilities(u.tenant_id)
        print(f"step8 interaction_caps ok keys={list(interaction_caps)[:3] if isinstance(interaction_caps, dict) else interaction_caps}")

        from app.core.authorization import AuthorizationContext
        authz = AuthorizationContext.from_user(u)
        module_keys = job_ctx.active_module_keys or None
        entries = get_module_router(db=db).workspace_entries(authz, module_keys)
        print(f"step9 workspace_entries={len(entries)}")
        print("ALL_OK")
    except Exception:
        print("=== EXCEPTION CAUGHT ===")
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    main()
