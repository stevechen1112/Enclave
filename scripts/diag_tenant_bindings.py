"""診斷：租戶、模組綁定、職能指派狀態。"""
from app.db.session import SessionLocal
from app.models.mka import (
    JobRole,
    TenantModuleBinding,
    UserJobRoleAssignment,
)
from app.models.tenant import Tenant


def main() -> None:
    db = SessionLocal()
    try:
        tenants = db.query(Tenant).all()
        for t in tenants:
            print(f"tenant name={t.name} id={t.id}")
        bindings = db.query(TenantModuleBinding).all()
        print(f"bindings={len(bindings)}")
        for b in bindings:
            print(
                f"  tenant_id={b.tenant_id} module={b.module_key} "
                f"enabled={b.enabled} cfg_ver={getattr(b, 'config_version', None)}"
            )
        roles = db.query(JobRole).all()
        print(f"job_roles={len(roles)}")
        for r in roles:
            print(f"  role_key={r.role_key} tenant_id={r.tenant_id} active={r.is_active}")
        assigns = db.query(UserJobRoleAssignment).all()
        print(f"assignments={len(assigns)}")
        for a in assigns:
            print(
                f"  user_id={a.user_id} role_id={a.job_role_id} "
                f"active={a.is_active}"
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()
