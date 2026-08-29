from __future__ import annotations

import uuid

from app.services.workflow_form_handler import build_form_handler

training = build_form_handler("training_checklist")


def interview(ctx):
    from app.services.mka_persistence import MKARepository
    from app.services.task_engine import TaskResult

    repo = MKARepository(ctx.db)
    values = dict(ctx.inputs.get("values") or {})
    title = values.get("title") or ctx.inputs.get("title") or "未命名訪談"
    summary = values.get("summary") or ctx.inputs.get("summary") or ""
    raw_steps = values.get("steps") if "steps" in values else ctx.inputs.get("steps")
    steps = (
        [line.strip() for line in raw_steps.splitlines() if line.strip()]
        if isinstance(raw_steps, str)
        else list(raw_steps or [])
    )
    card = repo.create_knowhow(
        tenant_id=ctx.user.tenant_id,
        title=str(title),
        summary=str(summary),
        steps=steps,
        data={"source": "interview", "task_run_id": str(ctx.run.id)},
        owner_id=ctx.user.id,
    )
    card, approval = repo.submit_knowhow(
        tenant_id=ctx.user.tenant_id,
        knowhow_id=card.id,
        submitted_by=ctx.user.id,
        expected_version=card.version,
        idempotency_key=f"task-run-{ctx.run.id}-{uuid.uuid4().hex[:8]}",
        actor_roles=[ctx.user.role],
        is_superuser=bool(getattr(ctx.user, "is_superuser", False)),
    )
    return TaskResult(
        output_refs={
            "knowhow_card_id": str(card.id),
            "approval_id": str(approval.id),
            "knowhow_status": card.status,
        },
        provenance={
            "handler": "interview",
            "knowhow_card_id": str(card.id),
            "approval_id": str(approval.id),
        },
        next_status="waiting_review",
    )
