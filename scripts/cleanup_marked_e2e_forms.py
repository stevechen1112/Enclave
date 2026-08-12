"""Remove only explicitly marked form E2E data and its task/approval traces.

The command is a dry run by default.  The marker must start with ``UX-E2E-``
and is matched against top-level submitted form values, so normal operational
records are never selected by a broad tenant or status deletion.

Usage (inside the web container):
    python scripts/cleanup_marked_e2e_forms.py UX-E2E-20260813-quote --apply
"""
from __future__ import annotations

import argparse

from app.db.session import SessionLocal
from app.models.mka import FormInstance, MKAApprovalRequest, TaskRun, TaskRunEvent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("marker", help="exact top-level E2E marker in a form value")
    parser.add_argument("--apply", action="store_true", help="delete the selected E2E records")
    args = parser.parse_args()

    if not args.marker.startswith("UX-E2E-"):
        parser.error("marker must start with UX-E2E-")

    db = SessionLocal()
    try:
        forms = [
            row
            for row in db.query(FormInstance).all()
            if args.marker in {str(value) for value in (row.values_json or {}).values()}
        ]
        form_ids = {row.id for row in forms}
        approvals = db.query(MKAApprovalRequest).filter(
            MKAApprovalRequest.object_type == "form",
            MKAApprovalRequest.object_id.in_(form_ids),
        ).all() if form_ids else []
        runs = [
            row
            for row in db.query(TaskRun).all()
            if str((row.output_refs or {}).get("form_instance_id", ""))
            in {str(form_id) for form_id in form_ids}
        ]
        run_ids = {row.id for row in runs}
        events = db.query(TaskRunEvent).filter(TaskRunEvent.run_id.in_(run_ids)).all() if run_ids else []

        print(
            "matched "
            f"forms={len(forms)} approvals={len(approvals)} "
            f"task_runs={len(runs)} task_events={len(events)}"
        )
        for row in forms:
            print(f"form {row.id} status={row.status}")
        for row in runs:
            print(f"task_run {row.id} status={row.status}")

        if not args.apply:
            db.rollback()
            print("dry run; re-run with --apply to delete only these exact records")
            return 0

        for row in events:
            db.delete(row)
        for row in approvals:
            db.delete(row)
        for row in runs:
            db.delete(row)
        for row in forms:
            db.delete(row)
        db.commit()
        print("deleted marked E2E records")
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
