"""Public, domain-neutral Workflow Kernel contracts."""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping


WORKFLOW_CAPABILITY_KEYS = (
    "workflow.task",
    "workflow.form",
    "workflow.approval",
    "workflow.todo",
    "workflow.notification",
    "workflow.export",
)

_TASK_STATUS_TRANSITIONS = {
    "draft": frozenset({"in_progress", "failed"}),
    "in_progress": frozenset({"waiting_review", "executed", "failed"}),
    "waiting_review": frozenset({"approved", "rejected", "failed"}),
    "approved": frozenset({"executed", "exported", "failed"}),
    "rejected": frozenset({"draft", "failed"}),
    "executed": frozenset({"exported"}),
    "exported": frozenset(),
    "failed": frozenset({"draft"}),
}

TASK_STATUS_TRANSITIONS: Mapping[str, frozenset[str]] = MappingProxyType(
    _TASK_STATUS_TRANSITIONS
)
TERMINAL_TASK_STATUSES = frozenset({"exported"})


def can_transition_task(from_status: str, to_status: str) -> bool:
    return to_status in TASK_STATUS_TRANSITIONS.get(from_status, frozenset())
