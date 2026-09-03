"""Versioned, domain-neutral evidence contracts for pre-generation decisions."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
import hashlib
from typing import Any, Dict, Iterable, List, Literal, Optional

CONTRACT_VERSION = "2.0"
_SENSITIVE_TRACE_KEYS = {
    "api_key", "authorization", "content", "password", "prompt", "quote",
    "secret", "token",
}
ValueType = Literal[
    "text", "money", "quantity", "date", "ratio", "unit", "code",
    "name", "status", "list", "boolean",
]


class EvidenceState(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    ABSENT = "absent"
    CONFLICT = "conflict"
    INSUFFICIENT_CONTEXT = "insufficient_context"


class ResponseAction(str, Enum):
    ANSWER = "answer"
    ANSWER_PARTIAL = "answer_partial"
    CLARIFY = "clarify"
    ABSTAIN = "abstain"
    ESCALATE = "escalate"


class ExecutionStatus(str, Enum):
    OK = "ok"
    PROVIDER_ERROR = "provider_error"
    SCHEMA_ERROR = "schema_error"
    TIMEOUT = "timeout"
    PACK_FAILURE = "pack_failure"
    INTERNAL_ERROR = "internal_error"


@dataclass(frozen=True)
class NamedGap:
    requirement_id: str
    label: str
    reason_codes: tuple[str, ...]
    required: bool = True


@dataclass(frozen=True)
class EvidenceConflict:
    requirement_id: str
    conflict_key: str
    evidence_ids: tuple[str, ...]
    reason_code: str = "same_scope_value_conflict"


@dataclass(frozen=True)
class ReviewedScope:
    tenant_id: Optional[str] = None
    department_ids: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()
    kb_revision_id: Optional[str] = None
    knowledge_release_id: Optional[str] = None
    exhaustive: bool = False


@dataclass(frozen=True)
class AnswerSlot:
    """Backward-compatible name for the AnswerRequirement contract."""

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
    shape: str = "scalar"
    expected_cardinality: Optional[int] = None
    exhaustive: bool = False
    required_relations: List[str] = field(default_factory=list)
    schema_version: str = CONTRACT_VERSION

    @property
    def requirement_id(self) -> str:
        return self.slot_id


AnswerRequirement = AnswerSlot


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
    tenant_id: Optional[str] = None
    department_id: Optional[str] = None
    source_id: Optional[str] = None
    knowledge_release_id: Optional[str] = None
    effective_from: Optional[datetime] = None
    effective_to: Optional[datetime] = None
    relation_kinds: tuple[str, ...] = ()
    closed_scope_verified: bool = False
    evidence_id: Optional[str] = None
    conflict_key: Optional[str] = None


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
    value_type_valid: bool = True
    temporal_valid: bool = True
    derivation_valid: bool = True
    relation_closure_valid: bool = True
    cardinality_valid: bool = True
    admitted: int = 0


def _as_datetime(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime(value.year, value.month, value.day)
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def redact_trace_payload(value: Any) -> Any:
    """Minimize trace data while retaining stable correlation evidence."""
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).casefold() in _SENSITIVE_TRACE_KEYS:
                material = str(item).encode("utf-8")
                redacted[key] = {
                    "redacted": True,
                    "sha256": hashlib.sha256(material).hexdigest(),
                    "length": len(material),
                }
            else:
                redacted[key] = redact_trace_payload(item)
        return redacted
    if isinstance(value, (list, tuple)):
        return [redact_trace_payload(item) for item in value]
    return value


def _valid_value(value: Any, expected: str) -> bool:
    if expected in {"text", "code", "name", "status", "unit"}:
        return isinstance(value, str) and bool(value.strip())
    if expected in {"money", "quantity", "ratio"}:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "list":
        return isinstance(value, (list, tuple, set))
    if expected == "date":
        return _as_datetime(value) is not None
    return False


def _scope_matches(slot: AnswerSlot, item: EvidenceItem) -> bool:
    scope = slot.source_scope or {}
    actuals = {
        "tenant_id": item.tenant_id,
        "department_id": item.department_id,
        "source_id": item.source_id,
        "document_id": item.document_id,
        "document_revision": item.document_revision,
        "kb_revision_id": item.kb_revision_id,
        "knowledge_release_id": item.knowledge_release_id,
    }
    for key, expected in scope.items():
        actual = actuals.get(key)
        if isinstance(expected, (list, tuple, set)):
            if str(actual) not in {str(value) for value in expected}:
                return False
        elif expected is not None and str(actual) != str(expected):
            return False
    return True


def _temporal_matches(slot: AnswerSlot, item: EvidenceItem) -> bool:
    requirement = slot.temporal_requirement or {}
    if not requirement:
        return True
    at = _as_datetime(requirement.get("at") or requirement.get("valid_on"))
    if at is None:
        return not bool(requirement.get("required"))
    start = _as_datetime(item.effective_from)
    end = _as_datetime(item.effective_to)
    return (start is None or start <= at) and (end is None or at < end)


@dataclass
class EvidenceContract:
    slots: List[AnswerSlot]
    completeness_mode: str = "exact"
    contract_version: str = CONTRACT_VERSION
    reviewed_scope: ReviewedScope = field(default_factory=ReviewedScope)

    def evaluate(self, evidence: Iterable[EvidenceItem]) -> List[SlotCoverage]:
        items = list(evidence)
        rows: List[SlotCoverage] = []
        for slot in self.slots:
            matched = [item for item in items if item.slot_id == slot.slot_id]
            value_ok = all(
                item.value_type == slot.value_type
                and _valid_value(item.value, slot.value_type)
                for item in matched
            )
            entity_ok = all(
                not slot.entity_binding or item.entity_id == slot.entity_binding
                for item in matched
            )
            revision_ok = bool(matched) and all(item.active_revision for item in matched)
            source_ok = bool(matched) and all(
                item.acl_verified and bool(item.quote.strip()) and _scope_matches(slot, item)
                for item in matched
            )
            authority_ok = all(
                not slot.authority_requirement
                or item.authority_class in slot.authority_requirement
                for item in matched
            )
            temporal_ok = all(_temporal_matches(slot, item) for item in matched)
            derivation_ok = all(
                item.derivation in slot.allowed_derivation for item in matched
            )
            relations = {kind for item in matched for kind in item.relation_kinds}
            relation_ok = set(slot.required_relations).issubset(relations)
            admitted = sum(
                1
                for item in matched
                if item.value_type == slot.value_type
                and _valid_value(item.value, slot.value_type)
                and (not slot.entity_binding or item.entity_id == slot.entity_binding)
                and item.active_revision
                and item.acl_verified
                and bool(item.quote.strip())
                and _scope_matches(slot, item)
                and (
                    not slot.authority_requirement
                    or item.authority_class in slot.authority_requirement
                )
                and _temporal_matches(slot, item)
                and item.derivation in slot.allowed_derivation
            )
            count_ok = admitted >= slot.minimum_values
            cardinality_ok = (
                slot.expected_cardinality is None
                or admitted == slot.expected_cardinality
            )
            exhaustive_ok = not slot.exhaustive or (
                self.reviewed_scope.exhaustive
                and any(item.closed_scope_verified for item in matched)
            )
            reasons: list[str] = []
            if not count_ok:
                reasons.append("minimum_values_not_met")
            if matched and not value_ok:
                reasons.append("value_type_mismatch")
            if matched and not entity_ok:
                reasons.append("entity_binding_mismatch")
            if matched and not revision_ok:
                reasons.append("inactive_or_wrong_revision")
            if matched and not source_ok:
                reasons.append("source_scope_or_acl_missing")
            if matched and not authority_ok:
                reasons.append("authority_not_allowed")
            if matched and not temporal_ok:
                reasons.append("temporal_requirement_not_met")
            if matched and not derivation_ok:
                reasons.append("derivation_not_allowed")
            if not relation_ok:
                reasons.append("relation_closure_missing")
            if not cardinality_ok:
                reasons.append("expected_cardinality_mismatch")
            if not exhaustive_ok:
                reasons.append("closed_scope_not_verified")
            passed = all(
                (
                    count_ok, value_ok, entity_ok, revision_ok, source_ok,
                    authority_ok, temporal_ok, derivation_ok, relation_ok,
                    cardinality_ok, exhaustive_ok,
                )
            )
            rows.append(
                SlotCoverage(
                    slot.slot_id, len(matched), slot.minimum_values, entity_ok,
                    revision_ok, source_ok, authority_ok,
                    "PASS" if passed else "MISSING", list(dict.fromkeys(reasons)),
                    value_ok, temporal_ok, derivation_ok, relation_ok,
                    cardinality_ok and exhaustive_ok, admitted,
                )
            )
        return rows

    def decision(
        self,
        evidence: Iterable[EvidenceItem],
        *,
        execution_status: ExecutionStatus | str = ExecutionStatus.OK,
    ) -> Dict[str, Any]:
        status = ExecutionStatus(execution_status)
        coverage = self.evaluate(evidence)
        missing = [row.slot_id for row in coverage if row.result != "PASS"]
        required_ids = [slot.slot_id for slot in self.slots if slot.required]
        required_missing = [slot_id for slot_id in required_ids if slot_id in missing]
        answered = [row.slot_id for row in coverage if row.result == "PASS"]
        gaps = [
            asdict(
                NamedGap(
                    row.slot_id,
                    next(slot.label for slot in self.slots if slot.slot_id == row.slot_id),
                    tuple(row.reasons),
                    row.slot_id in required_ids,
                )
            )
            for row in coverage
            if row.result != "PASS"
        ]
        if status is not ExecutionStatus.OK:
            state = EvidenceState.PARTIAL if answered else EvidenceState.INSUFFICIENT_CONTEXT
            action = ResponseAction.ESCALATE
            legacy = "error"
        elif not required_missing:
            state, action, legacy = EvidenceState.COMPLETE, ResponseAction.ANSWER, "answer"
        elif answered:
            state, action, legacy = (
                EvidenceState.PARTIAL, ResponseAction.ANSWER_PARTIAL, "partial"
            )
        else:
            state = (
                EvidenceState.INSUFFICIENT_CONTEXT
                if any("binding" in reason for gap in gaps for reason in gap["reason_codes"])
                else EvidenceState.ABSENT
            )
            action = ResponseAction.CLARIFY if state is EvidenceState.INSUFFICIENT_CONTEXT else ResponseAction.ABSTAIN
            legacy = "abstain"
        return {
            "schema_version": self.contract_version,
            "complete": state is EvidenceState.COMPLETE,
            "decision": legacy,
            "evidence_state": state.value,
            "response_action": action.value,
            "execution_status": status.value,
            "answered_slots": answered,
            "answered_requirements": answered,
            "missing_slots": missing,
            "missing_requirements": gaps,
            "reviewed_scope": asdict(self.reviewed_scope),
            "coverage": [asdict(row) for row in coverage],
        }
