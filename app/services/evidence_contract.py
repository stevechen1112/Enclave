"""Domain-neutral answer slots, evidence and coverage decisions."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Literal, Optional

ValueType = Literal["text", "money", "quantity", "date", "ratio", "unit", "code", "name", "status", "list", "boolean"]


@dataclass(frozen=True)
class AnswerSlot:
    slot_id: str
    label: str
    value_type: ValueType = "text"
    required: bool = True
    minimum_values: int = 1
    entity_binding: Optional[str] = None
    source_scope: Dict[str, Any] = field(default_factory=dict)
    authority_requirement: List[str] = field(default_factory=list)
    temporal_requirement: Dict[str, Any] = field(default_factory=dict)
    allowed_derivation: List[str] = field(default_factory=lambda: ["direct"])


@dataclass(frozen=True)
class EvidenceItem:
    slot_id: str
    value: Any
    value_type: str
    document_id: str
    document_revision: str
    unit_id: str
    unit_type: str
    quote: str
    entity_id: Optional[str] = None
    authority_class: str = "primary_document"
    kb_revision_id: Optional[str] = None
    locator: Dict[str, Any] = field(default_factory=dict)
    acl_verified: bool = False
    active_revision: bool = False
    derivation: str = "direct"


@dataclass(frozen=True)
class SlotCoverage:
    slot_id: str
    found: int
    required: int
    entity_consistent: bool
    revision_valid: bool
    source_sufficient: bool
    authority_valid: bool
    result: str
    reasons: List[str] = field(default_factory=list)


@dataclass
class EvidenceContract:
    slots: List[AnswerSlot]
    completeness_mode: str = "exact"

    def evaluate(self, evidence: Iterable[EvidenceItem]) -> List[SlotCoverage]:
        items = list(evidence)
        rows: List[SlotCoverage] = []
        for slot in self.slots:
            matched = [e for e in items if e.slot_id == slot.slot_id]
            reasons: List[str] = []
            entity_ok = all(not slot.entity_binding or e.entity_id == slot.entity_binding for e in matched)
            revision_ok = bool(matched) and all(e.active_revision for e in matched)
            source_ok = bool(matched) and all(e.acl_verified and bool(e.quote.strip()) for e in matched)
            authority_ok = all(not slot.authority_requirement or e.authority_class in slot.authority_requirement for e in matched)
            derivation_ok = all(e.derivation in slot.allowed_derivation for e in matched)
            count_ok = len(matched) >= slot.minimum_values
            if not count_ok: reasons.append("minimum_values_not_met")
            if matched and not entity_ok: reasons.append("entity_binding_mismatch")
            if matched and not revision_ok: reasons.append("inactive_revision")
            if matched and not source_ok: reasons.append("source_or_acl_missing")
            if matched and not authority_ok: reasons.append("authority_not_allowed")
            if matched and not derivation_ok: reasons.append("derivation_not_allowed")
            passed = count_ok and entity_ok and revision_ok and source_ok and authority_ok and derivation_ok
            rows.append(SlotCoverage(slot.slot_id, len(matched), slot.minimum_values, entity_ok, revision_ok,
                                     source_ok, authority_ok, "PASS" if passed else "MISSING", reasons))
        return rows

    def decision(self, evidence: Iterable[EvidenceItem]) -> Dict[str, Any]:
        coverage = self.evaluate(evidence)
        missing = [r.slot_id for r in coverage if r.result != "PASS"]
        required_missing = [s.slot_id for s in self.slots if s.required and s.slot_id in missing]
        return {
            "complete": not required_missing,
            "decision": "answer" if not required_missing else ("partial" if len(required_missing) < len([s for s in self.slots if s.required]) else "abstain"),
            "answered_slots": [r.slot_id for r in coverage if r.result == "PASS"],
            "missing_slots": missing,
            "coverage": [asdict(r) for r in coverage],
        }

