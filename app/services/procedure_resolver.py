"""Procedure branch selection with explicit completeness reporting."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional


@dataclass(frozen=True)
class ProcedureStep:
    key: str
    sequence: int
    instruction: str
    actor: Optional[str] = None
    conditions: Dict[str, str] = field(default_factory=dict)
    exceptions: List[str] = field(default_factory=list)
    completion: Optional[str] = None
    source_ref: Dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ProcedureResolution:
    status: str
    steps: List[ProcedureStep]
    missing_phases: List[str]
    reason: str = ""


def resolve_procedure(steps: Iterable[ProcedureStep], context: Dict[str, str], required_phases: Iterable[str] = ()) -> ProcedureResolution:
    selected = []
    for step in sorted(steps, key=lambda s: s.sequence):
        if all(str(context.get(k, "")).casefold() == str(v).casefold() for k, v in step.conditions.items()):
            selected.append(step)
    required = list(required_phases)
    present = {s.key for s in selected}
    missing = [p for p in required if p not in present]
    if not selected:
        return ProcedureResolution("abstain", [], required, "no branch matches the supplied conditions")
    return ProcedureResolution("complete" if not missing else "partial", selected, missing,
                               "" if not missing else "required phases are not supported by evidence")

