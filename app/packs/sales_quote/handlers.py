from __future__ import annotations

import re
import uuid

from app.services.task_engine import TaskResult


def _lookup_price(db, tenant_id, part_number: str):
    from app.models.document import DocumentChunk

    rows = db.query(DocumentChunk).filter(
        DocumentChunk.tenant_id == tenant_id,
        DocumentChunk.text.contains(part_number),
    ).limit(5).all()
    exact = re.compile(
        re.escape(part_number)
        + r"[^\d]{0,20}?(?:單價|價格|price)[^\d]{0,10}([0-9,]+(?:\.[0-9]+)?)",
        re.IGNORECASE,
    )
    generic = re.compile(r"(?:單價|價格)\s*[：:為是]?\s*([0-9,]+(?:\.[0-9]+)?)")
    for chunk in rows:
        match = exact.search(chunk.text or "") or generic.search(chunk.text or "")
        if not match:
            continue
        try:
            value = float(match.group(1).replace(",", ""))
        except ValueError:
            continue
        return {"value": value, "ref": f"doc:{chunk.document_id}", "confidence": 0.7}
    return None


def quote(ctx):
    from app.services.fixed_form import get_form_registry
    from app.services.workflow_repository import WorkflowRepository

    repo = WorkflowRepository(ctx.db)
    values = dict(ctx.inputs.get("values") or {})
    for key in ("quantity", "unit_price", "tax_rate"):
        if key in values and isinstance(values[key], str):
            try:
                raw = values[key].replace(",", "").strip()
                values[key] = float(raw) if "." in raw else int(raw)
            except (TypeError, ValueError):
                pass
    sources = {
        field: {
            "source": meta.get("source", "user"),
            "ref": meta.get("ref"),
            "confidence": meta.get("confidence"),
        }
        for field, meta in (ctx.inputs.get("sources") or {}).items()
        if isinstance(meta, dict)
    }
    if not values.get("unit_price") and values.get("part_number"):
        hit = _lookup_price(ctx.db, ctx.user.tenant_id, str(values["part_number"]))
        if hit:
            values["unit_price"] = hit["value"]
            sources["unit_price"] = {
                "source": "knowledge",
                "ref": hit["ref"],
                "confidence": hit["confidence"],
            }
    instance = repo.create_form_instance(
        tenant_id=ctx.user.tenant_id,
        owner_id=ctx.user.id,
        form_key="quote",
        values=values,
        provenance={
            "task_run_id": str(ctx.run.id),
            "sources": ctx.inputs.get("sources") or {},
        },
        module_key=ctx.definition.module_key,
        scene_context=ctx.job_ctx.scene or {},
    )
    instance = repo.calculate_form(
        tenant_id=ctx.user.tenant_id,
        instance_id=instance.id,
        actor_id=ctx.user.id,
        actor_roles=[ctx.user.role],
        is_superuser=bool(getattr(ctx.user, "is_superuser", False)),
        expected_version=instance.record_version,
    )
    calculated = (instance.calculation_snapshot or {}).get("calculated") or {}
    for field_name in calculated:
        sources[field_name] = {
            "source": "rule",
            "ref": f"formula:{field_name}",
            "confidence": 1.0,
        }
    schema = get_form_registry().get("quote")
    final_values = dict(instance.values_json or {})
    missing = [
        field.name
        for field in (schema.fields if schema else [])
        if field.required and final_values.get(field.name) in (None, "")
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
            "form_key": "quote",
            "form_status": instance.status,
            **({"approval_id": approval_id} if approval_id else {}),
        },
        field_sources=sources,
        provenance={
            "handler": "quote",
            "form_instance_id": str(instance.id),
            "calculation_snapshot": instance.calculation_snapshot or {},
            "missing_fields": missing,
            **({"approval_id": approval_id} if approval_id else {}),
        },
        next_status="waiting_review" if approval_id else "in_progress",
    )
