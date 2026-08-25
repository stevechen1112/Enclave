"""診斷模組 allowlist 與單一使用者可用模組。"""
import sys
from app.demo.manifest import DEMO_PERSONAS

from app.db.session import SessionLocal
from app.models.mka import JobModule
from app.models.user import User
from app.services.job_context import build_effective_job_context
from app.services.module_registry import get_module_registry


def main() -> None:
    email = sys.argv[1] if len(sys.argv) > 1 else str(DEMO_PERSONAS["sales"]["email"])
    db = SessionLocal()
    try:
        print("=== JobModule 全量 ===")
        for m in db.query(JobModule).all():
            print(
                f"  {m.module_key} status={m.status} tenant={m.tenant_id} "
                f"allowed_job={m.allowed_job_role_keys} allowed_roles={m.allowed_roles}"
            )
        u = db.query(User).filter(User.email == email).first()
        if not u:
            print(f"USER_NOT_FOUND {email}")
            return
        job_ctx = build_effective_job_context(db, u)
        print("=== EffectiveJobContext ===")
        print(f"  security_roles={list(job_ctx.security_roles)}")
        print(f"  active_job_role_keys={list(job_ctx.active_job_role_keys)}")
        print(f"  active_job_role={job_ctx.active_job_role}")
        reg = get_module_registry(db)
        avail = reg.get_available_modules(
            tenant_id=u.tenant_id,
            user_roles=list(job_ctx.security_roles),
            user_department_ids=list(job_ctx.department_ids),
            job_role_keys=list(job_ctx.active_job_role_keys),
        )
        print(f"=== available ({len(avail)}) ===")
        for m in avail:
            print(f"  {m.get('module_key')}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
