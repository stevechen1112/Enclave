"""Generic form-backed Workflow handler factory with no application vocabulary."""

from __future__ import annotations

import uuid
from typing import Any


def build_form_handler(form_key: str):
    from app.services.task_engine import TaskResult

    def handler(ctx: Any) -> TaskResult:
        from app.services.fixed_form import get_form_registry
        from app.services.workflow_repository import WorkflowRepository

        repo = WorkflowRepository(ctx.db)
        instance = repo.create_form_instance(
            tenant_id=ctx.user.tenant_id,
            owner_id=ctx.user.id,
            form_key=form_key,
            values=ctx.inputs.get("values") or {},
            provenance={
                "task_run_id": str(ctx.run.id),
                "sources": ctx.inputs.get("sources") or {},
            },
            module_key=ctx.definition.module_key,
            scene_context=ctx.job_ctx.scene or {},
        )
        sources = {
            field: {
                "source": meta.get("source", "user"),
                "ref": meta.get("ref"),
                "confidence": meta.get("confidence"),
            }
            for field, meta in (ctx.inputs.get("sources") or {}).items()
            if isinstance(meta, dict)
        }
        schema = get_form_registry().get(form_key)
        values = dict(instance.values_json or {})
        missing = [
            field.name
            for field in (schema.fields if schema else [])
            if field.required and values.get(field.name) in (None, "")
        ]
        approval_id = None
        if not missing:
            instance, approval = repo.submit_form(
                tenant_id=ctx.user.tenant_id,
                instance_id=instance.id,
                submitted_by=ctx.user.id,
                expected_version=instance.record_version,
                idempotency_key=f"task-run-{ctx.run.id}-{uuid.uuid4().hex[:8]}",
            )
            approval_id = str(approval.id)
        return TaskResult(
            output_refs={
                "form_instance_id": str(instance.id),
                "form_key": form_key,
                "form_status": instance.status,
                **({"approval_id": approval_id} if approval_id else {}),
            },
            field_sources=sources,
            provenance={
                "handler": form_key,
                "form_instance_id": str(instance.id),
                "missing_fields": missing,
                **({"approval_id": approval_id} if approval_id else {}),
            },
            next_status="waiting_review" if approval_id else "in_progress",
        )

    return handler
