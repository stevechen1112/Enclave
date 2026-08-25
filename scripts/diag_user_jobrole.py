"""診斷單一使用者的職能指派與模組可見性。"""
import sys
from app.demo.manifest import DEMO_PERSONAS

from app.db.session import SessionLocal
from app.models.mka import JobRole, UserJobRoleAssignment
from app.models.user import User


def main() -> None:
    email = sys.argv[1] if len(sys.argv) > 1 else str(DEMO_PERSONAS["sales"]["email"])
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.email == email).first()
        if not u:
            print(f"USER_NOT_FOUND: {email}")
            return
        print(f"user_id={u.id} tenant={u.tenant_id} role={u.role}")
        print(f"active_job_role_id={getattr(u, 'active_job_role_id', None)}")
        assigns = (
            db.query(UserJobRoleAssignment)
            .filter(UserJobRoleAssignment.user_id == u.id)
            .all()
        )
        print(f"assigns={[(str(a.job_role_id), a.is_active) for a in assigns]}")
        roles = db.query(JobRole).filter(JobRole.tenant_id == u.tenant_id).all()
        print(f"roles={[(r.role_key, str(r.id)) for r in roles]}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
