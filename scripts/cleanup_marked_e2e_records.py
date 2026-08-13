"""Safely remove one explicitly marked production E2E dataset.

The command is a dry run unless ``--apply`` is supplied.  Selection is based
on a required ``UX-E2E-`` marker found recursively in task/form/knowhow data;
normal tenant records are never selected by tenant, date, role, or status.

Voice sessions do not contain the E2E task marker, so their exact UUIDs may be
supplied separately with ``--voice-session-id``.
"""
from __future__ import annotations

import argparse
from typing import Any
from uuid import UUID

from app.db.session import SessionLocal
from app.models.mka import (
    FormInstance,
    InteractionSession,
    KnowhowCardModel,
    KnowhowLineage,
    MKAApprovalRequest,
    MKAReviewReminder,
    MKATaskCost,
    TaskRun,
    TaskRunEvent,
)


def _contains(value: Any, marker: str) -> bool:
    if isinstance(value, str):
        return marker in value
    if isinstance(value, dict):
        return any(_contains(key, marker) or _contains(item, marker) for key, item in value.items())
    if isinstance(value, (list, tuple, set)):
        return any(_contains(item, marker) for item in value)
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("marker", help="E2E marker substring; must start with UX-E2E-")
    parser.add_argument(
        "--voice-session-id",
        action="append",
        default=[],
        help="exact E2E interaction-session UUID; may be supplied more than once",
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.marker.startswith("UX-E2E-") or len(args.marker) < 16:
        parser.error("marker must be a specific value starting with UX-E2E-")
    try:
        voice_session_ids = {UUID(value) for value in args.voice_session_id}
    except ValueError as exc:
        parser.error(f"invalid --voice-session-id: {exc}")

    db = SessionLocal()
    try:
        runs = [
            row for row in db.query(TaskRun).all()
            if args.marker in (row.idempotency_key or "")
            or _contains(row.input_snapshot, args.marker)
            or _contains(row.provenance, args.marker)
            or _contains(row.output_refs, args.marker)
        ]
        output_form_ids = {
            UUID(str(value))
            for row in runs
            for value in [(row.output_refs or {}).get("form_instance_id")]
            if value
        }
        output_knowhow_ids = {
            UUID(str(value))
            for row in runs
            for value in [(row.output_refs or {}).get("knowhow_card_id")]
            if value
        }
        forms = [
            row for row in db.query(FormInstance).all()
            if row.id in output_form_ids
            or _contains(row.values_json, args.marker)
            or _contains(row.provenance_json, args.marker)
        ]
        knowhow = [
            row for row in db.query(KnowhowCardModel).all()
            if row.id in output_knowhow_ids
            or _contains(row.card_id, args.marker)
            or _contains(row.title, args.marker)
            or _contains(row.summary, args.marker)
        ]
        form_ids = {row.id for row in forms}
        knowhow_ids = {row.id for row in knowhow}
        object_ids = form_ids | knowhow_ids
        approvals = (
            db.query(MKAApprovalRequest)
            .filter(MKAApprovalRequest.object_id.in_(object_ids))
            .all()
            if object_ids else []
        )
        run_ids = {row.id for row in runs}
        events = (
            db.query(TaskRunEvent).filter(TaskRunEvent.run_id.in_(run_ids)).all()
            if run_ids else []
        )
        lineage = (
            db.query(KnowhowLineage).filter(KnowhowLineage.card_id.in_(knowhow_ids)).all()
            if knowhow_ids else []
        )
        reminders = (
            db.query(MKAReviewReminder).filter(MKAReviewReminder.card_id.in_(knowhow_ids)).all()
            if knowhow_ids else []
        )
        sessions = (
            db.query(InteractionSession)
            .filter(InteractionSession.id.in_(voice_session_ids))
            .all()
            if voice_session_ids else []
        )
        found_session_ids = {row.id for row in sessions}
        missing_session_ids = voice_session_ids - found_session_ids
        costs = (
            db.query(MKATaskCost)
            .filter(MKATaskCost.task_id.in_([str(value) for value in voice_session_ids]))
            .all()
            if voice_session_ids else []
        )

        print(
            "matched "
            f"task_runs={len(runs)} task_events={len(events)} "
            f"forms={len(forms)} approvals={len(approvals)} "
            f"knowhow={len(knowhow)} lineage={len(lineage)} reminders={len(reminders)} "
            f"voice_sessions={len(sessions)} voice_costs={len(costs)}"
        )
        for row in runs:
            print(f"task_run {row.id} task={row.task_key} status={row.status}")
        for row in forms:
            print(
                f"form {row.id} status={row.status} "
                f"export_artifacts={row.export_artifacts or []}"
            )
        for row in knowhow:
            print(f"knowhow {row.id} status={row.status} title={row.title}")
        for row in sessions:
            print(f"voice_session {row.id} state={row.state}")
        for value in sorted(missing_session_ids, key=str):
            print(f"voice_session_missing {value}")

        if not args.apply:
            db.rollback()
            print("dry run; inspect every ID, then re-run with --apply")
            return 0

        for rows in (events, runs, forms, lineage, reminders, approvals, knowhow, costs, sessions):
            for row in rows:
                db.delete(row)
            db.flush()
        db.commit()
        print("deleted only the matched E2E records")
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
