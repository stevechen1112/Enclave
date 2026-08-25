"""Pre-generation evidence orchestration and answer-tier decision."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List

from app.services.evidence_contract import EvidenceContract, EvidenceItem


@dataclass(frozen=True)
class EvidenceDecision:
    tier: int
    action: str
    evidence: List[EvidenceItem]
    coverage: dict
    reason: str


def decide_evidence(contract: EvidenceContract, evidence: Iterable[EvidenceItem], *, operation: str = "lookup") -> EvidenceDecision:
    items = list(evidence)
    coverage = contract.decision(items)
    if coverage["decision"] == "abstain":
        return EvidenceDecision(3, "abstain", [], coverage, "no required slot has valid evidence")
    if coverage["decision"] == "partial":
        passed = set(coverage["answered_slots"])
        return EvidenceDecision(3, "partial", [e for e in items if e.slot_id in passed], coverage, "required evidence is incomplete")
    if operation == "aggregate":
        if not all(e.derivation in {"count", "sum", "min", "max"} for e in items):
            return EvidenceDecision(3, "abstain", [], coverage, "aggregate lacks deterministic derivation")
        return EvidenceDecision(0, "answer", items, coverage, "deterministic aggregate")
    if all(e.unit_type in {"row", "field", "form"} for e in items):
        return EvidenceDecision(1, "answer", items, coverage, "structured evidence")
    return EvidenceDecision(2, "answer", items, coverage, "source-grounded narrative evidence")

