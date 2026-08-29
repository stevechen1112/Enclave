"""Composition adapter for application-owned approval object side effects."""

from __future__ import annotations

from typing import Any


def apply_application_approval(
    db: Any,
    approval: Any,
    *,
    action: str,
    reviewer_id: Any,
    reason: str = "",
) -> None:
    if approval.object_type == "knowhow":
        from app.packs.training_knowhow.approval import apply_decision

        apply_decision(
            db,
            approval,
            action=action,
            reviewer_id=reviewer_id,
            reason=reason,
        )
        return
    raise ValueError(f"unsupported application approval object: {approval.object_type}")


def application_approval_task_reference_key(object_type: str) -> str | None:
    if object_type == "knowhow":
        from app.packs.training_knowhow.approval import task_reference_key

        return task_reference_key()
    return None


def application_approval_module_key(object_type: str) -> str | None:
    return "training_knowhow" if object_type == "knowhow" else None
