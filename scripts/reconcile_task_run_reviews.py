"""Reconcile legacy task runs after task-review lifecycle deployment.

Older task runs can remain in ``waiting_review`` even though their linked form
or know-how approval has already reached a final decision.  Run this once after
deploying the lifecycle bridge.  It is dry-run by default and only changes
runs whose approval has a recorded final decision.

Usage (inside the web container):
    python scripts/reconcile_task_run_reviews.py --apply
"""
from __future__ import annotations

import argparse
from uuid import UUID

from app.db.session import SessionLocal
from app.models.mka import MKAApprovalRequest, TaskRun
from app.services.mka_persistence import MKARepository


FINAL_STATUSES = {"approved", "rejected", "changes_requested"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="persist reconciled task runs")
    args = parser.parse_args()

    db = SessionLocal()
    updated = 0
    skipped = 0
    try:
        approvals = db.query(MKAApprovalRequest).filter(
            MKAApprovalRequest.status.in_(FINAL_STATUSES)
        ).all()
        repo = MKARepository(db)
        for approval in approvals:
            decisions = list(approval.decision_log or [])
            if not decisions:
                skipped += 1
                continue
            decision = decisions[-1]
            reviewer_id = decision.get("reviewer_id")
            action = decision.get("action")
            if not reviewer_id or not action:
                skipped += 1
                continue
            reference_key = {
                "form": "form_instance_id",
                "knowhow": "knowhow_card_id",
            }.get(approval.object_type)
            if reference_key is None:
                skipped += 1
                continue
            linked_runs = [
                run
                for run in db.query(TaskRun).filter(
                    TaskRun.tenant_id == approval.tenant_id,
                    TaskRun.status == "waiting_review",
                ).all()
                if str((run.output_refs or {}).get(reference_key, "")) == str(approval.object_id)
            ]
            if not linked_runs:
                continue
            repo._sync_task_run_for_approval(  # intentional operational reuse
                approval,
                reviewer_id=UUID(str(reviewer_id)),
                action=str(action),
                reason=str(decision.get("reason") or ""),
            )
            updated += len(linked_runs)

        if args.apply:
            db.commit()
            print(f"reconciled approvals: {updated}; skipped: {skipped}")
        else:
            db.rollback()
            print(f"dry run — would reconcile approvals: {updated}; skipped: {skipped}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
