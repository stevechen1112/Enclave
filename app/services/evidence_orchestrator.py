"""Canonical, deterministic pre-generation EvidenceDecision engine."""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, List, Mapping

from app.services.evidence_contract import (
    EvidenceConflict,
    EvidenceContract,
    EvidenceItem,
    EvidenceState,
    ExecutionStatus,
    ResponseAction,
    redact_trace_payload,
)

DECISION_SCHEMA_VERSION = "2.0"
DERIVATION_REGISTRY = frozenset(
    {"direct", "count", "sum", "min", "max", "date_compare", "set", "same_record", "procedure_order"}
)


@dataclass(frozen=True)
class EvidenceDecision:
    # Compatibility surface used by existing callers.
    tier: int
    action: str
    evidence: List[EvidenceItem]
    coverage: dict[str, Any]
    reason: str
    # Canonical KQ2 contract.
    decision_id: str = ""
    schema_version: str = DECISION_SCHEMA_VERSION
    query_spec_version: str = "2.0"
    contract_version: str = "2.0"
    evidence_state: str = EvidenceState.INSUFFICIENT_CONTEXT.value
    response_action: str = ResponseAction.CLARIFY.value
    execution_status: str = ExecutionStatus.OK.value
    verified_claims: List[EvidenceItem] = field(default_factory=list)
    answered_requirements: List[str] = field(default_factory=list)
    missing_requirements: List[dict[str, Any]] = field(default_factory=list)
    conflicts: List[EvidenceConflict] = field(default_factory=list)
    near_evidence: List[EvidenceItem] = field(default_factory=list)
    reviewed_scope: dict[str, Any] = field(default_factory=dict)
    reason_codes: List[str] = field(default_factory=list)
    stage_trace: List[dict[str, Any]] = field(default_factory=list)
    trace_id: str = ""
    decision_hash: str = ""
    kb_revision_id: str | None = None
    knowledge_release_id: str | None = None
    pack_versions: dict[str, str] = field(default_factory=dict)

    def to_dict(self, *, include_evidence: bool = False) -> dict[str, Any]:
        payload = asdict(self)
        if not include_evidence:
            payload["evidence"] = [_evidence_ref(item) for item in self.evidence]
            payload["verified_claims"] = [
                _evidence_ref(item) for item in self.verified_claims
            ]
            payload["near_evidence"] = [
                _evidence_ref(item) for item in self.near_evidence
            ]
        return redact_trace_payload(payload)


def _evidence_ref(item: EvidenceItem) -> dict[str, Any]:
    value_hash = hashlib.sha256(
        json.dumps(item.value, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return {
        "evidence_id": item.evidence_id or item.unit_id,
        "requirement_id": item.slot_id,
        "unit_id": item.unit_id,
        "document_id": item.document_id,
        "document_revision": item.document_revision,
        "kb_revision_id": item.kb_revision_id,
        "knowledge_release_id": item.knowledge_release_id,
        "value_hash": value_hash,
    }


def _temporal_overlap(left: EvidenceItem, right: EvidenceItem) -> bool:
    floor = datetime.min.replace(tzinfo=timezone.utc)
    ceiling = datetime.max.replace(tzinfo=timezone.utc)
    left_start, left_end = left.effective_from or floor, left.effective_to or ceiling
    right_start, right_end = right.effective_from or floor, right.effective_to or ceiling
    return left_start < right_end and right_start < left_end


def _detect_conflicts(items: list[EvidenceItem]) -> list[EvidenceConflict]:
    groups: dict[tuple[Any, ...], list[EvidenceItem]] = {}
    for item in items:
        if not item.conflict_key:
            continue
        key = (
            item.slot_id,
            item.conflict_key,
            item.entity_id,
            item.tenant_id,
            item.department_id,
            item.kb_revision_id,
            item.knowledge_release_id,
        )
        groups.setdefault(key, []).append(item)
    conflicts: list[EvidenceConflict] = []
    for key, group in groups.items():
        values = {
            json.dumps(item.value, sort_keys=True, default=str) for item in group
        }
        overlaps = any(
            _temporal_overlap(left, right)
            for index, left in enumerate(group)
            for right in group[index + 1 :]
            if left.value != right.value
        )
        if len(values) > 1 and overlaps:
            conflicts.append(
                EvidenceConflict(
                    requirement_id=str(key[0]),
                    conflict_key=str(key[1]),
                    evidence_ids=tuple(
                        sorted(item.evidence_id or item.unit_id for item in group)
                    ),
                )
            )
    return conflicts


def _decision_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
    ).hexdigest()


def decide_evidence(
    contract: EvidenceContract,
    evidence: Iterable[EvidenceItem],
    *,
    operation: str = "lookup",
    query_spec: Mapping[str, Any] | None = None,
    execution_status: ExecutionStatus | str = ExecutionStatus.OK,
    pack_versions: Mapping[str, str] | None = None,
) -> EvidenceDecision:
    """Run admission→applicability→completeness and issue one decision."""
    parse_started = time.perf_counter()
    items = list(evidence)
    status = ExecutionStatus(execution_status)
    spec = dict(query_spec or {})
    parse_ms = (time.perf_counter() - parse_started) * 1000
    applicability_started = time.perf_counter()
    coverage = contract.decision(items, execution_status=status)
    applicability_ms = (time.perf_counter() - applicability_started) * 1000
    select_started = time.perf_counter()
    passed = set(coverage["answered_requirements"])
    verified = [item for item in items if item.slot_id in passed]
    near = [item for item in items if item.slot_id not in passed]
    conflicts = _detect_conflicts(verified)
    select_ms = (time.perf_counter() - select_started) * 1000
    reason_codes: list[str] = []
    completeness_started = time.perf_counter()

    if status is not ExecutionStatus.OK:
        state = EvidenceState(coverage["evidence_state"])
        response_action = ResponseAction.ESCALATE
        action, tier, reason = "error", 3, f"execution failed: {status.value}"
        verified = []
        reason_codes.append(f"execution.{status.value}")
    elif conflicts:
        state, response_action = EvidenceState.CONFLICT, ResponseAction.ESCALATE
        action, tier, reason = "conflict", 3, "same-scope evidence conflicts"
        verified = []
        reason_codes.append("select.same_scope_value_conflict")
    elif coverage["decision"] == "abstain":
        state = EvidenceState(coverage["evidence_state"])
        response_action = ResponseAction(coverage["response_action"])
        action, tier = "abstain", 3
        reason = "no required requirement has valid evidence"
        reason_codes.append(f"completeness.{state.value}")
    elif coverage["decision"] == "partial":
        state, response_action = EvidenceState.PARTIAL, ResponseAction.ANSWER_PARTIAL
        action, tier, reason = "partial", 3, "required evidence is incomplete"
        reason_codes.append("completeness.required_requirement_missing")
    elif operation == "aggregate" and not all(
        item.derivation in {"count", "sum", "min", "max"} for item in verified
    ):
        state, response_action = EvidenceState.INSUFFICIENT_CONTEXT, ResponseAction.ABSTAIN
        action, tier, reason = "abstain", 3, "aggregate lacks deterministic derivation"
        near, verified = items, []
        reason_codes.append("select.aggregate_derivation_not_registered")
    else:
        state, response_action, action = (
            EvidenceState.COMPLETE,
            ResponseAction.ANSWER,
            "answer",
        )
        if operation == "aggregate":
            tier, reason = 0, "deterministic aggregate"
        elif verified and all(
            item.unit_type in {"row", "field", "form"} for item in verified
        ):
            tier, reason = 1, "structured evidence"
        else:
            tier, reason = 2, "source-grounded narrative evidence"
        reason_codes.append("decision.verified")

    completeness_ms = (time.perf_counter() - completeness_started) * 1000

    trace = [
        {
            "stage": "parse",
            "status": "blocked" if spec.get("ambiguity") else "ok",
            "query_spec_version": str(spec.get("plan_version") or "2.0"),
            "ambiguity_count": len(spec.get("ambiguity") or []),
            "latency_ms": round(parse_ms, 6),
        },
        {"stage": "retrieve", "status": status.value, "candidate_count": len(items), "latency_ms": None},
        {
            "stage": "select",
            "status": "conflict" if conflicts else "ok",
            "verified_count": len(verified),
            "near_evidence_count": len(near),
            "latency_ms": round(select_ms, 6),
        },
        {
            "stage": "applicability",
            "status": "ok" if not near else "filtered",
            "rejected_count": len(near),
            "latency_ms": round(applicability_ms, 6),
        },
        {
            "stage": "completeness",
            "status": state.value,
            "answered_count": len(coverage["answered_requirements"]),
            "missing_count": len(coverage["missing_requirements"]),
            "latency_ms": round(completeness_ms, 6),
        },
        {
            "stage": "conversation",
            "status": "needs_context" if state is EvidenceState.INSUFFICIENT_CONTEXT else "ok",
            "latency_ms": 0.0,
        },
    ]
    stable = {
        "schema_version": DECISION_SCHEMA_VERSION,
        "query_spec_version": str(spec.get("plan_version") or "2.0"),
        "contract_version": contract.contract_version,
        "evidence_state": state.value,
        "response_action": response_action.value,
        "execution_status": status.value,
        "verified_claims": [_evidence_ref(item) for item in verified],
        "near_evidence": [_evidence_ref(item) for item in near],
        "missing_requirements": coverage["missing_requirements"],
        "conflicts": [asdict(conflict) for conflict in conflicts],
        "reviewed_scope": coverage["reviewed_scope"],
        "reason_codes": reason_codes,
        "pack_versions": dict(sorted((pack_versions or {}).items())),
    }
    digest = _decision_hash(stable)
    return EvidenceDecision(
        tier=tier,
        action=action,
        evidence=verified,
        coverage=coverage,
        reason=reason,
        decision_id=digest[:24],
        query_spec_version=stable["query_spec_version"],
        contract_version=contract.contract_version,
        evidence_state=state.value,
        response_action=response_action.value,
        execution_status=status.value,
        verified_claims=verified,
        answered_requirements=list(coverage["answered_requirements"]),
        missing_requirements=list(coverage["missing_requirements"]),
        conflicts=conflicts,
        near_evidence=near,
        reviewed_scope=dict(coverage["reviewed_scope"]),
        reason_codes=reason_codes,
        stage_trace=trace,
        trace_id=digest[:32],
        decision_hash=digest,
        kb_revision_id=contract.reviewed_scope.kb_revision_id,
        knowledge_release_id=contract.reviewed_scope.knowledge_release_id,
        pack_versions=dict(sorted((pack_versions or {}).items())),
    )
