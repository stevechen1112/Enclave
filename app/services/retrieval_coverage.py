"""Conservative slot coverage over retrieved evidence before generation."""
from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from app.services.evidence_contract import (
    EvidenceState,
    ExecutionStatus,
    ResponseAction,
)


SLOT_RULES = {
    "unit_price": ("單價", re.compile(r"單價.{0,20}\d")),
    "total_price": ("總價", re.compile(r"(?:總價|總計|合計).{0,20}\d")),
    "amount": ("金額", re.compile(r"(?:金額|價款|費用|合計).{0,20}\d")),
    "date": ("日期", re.compile(r"(?:19|20)\d{2}[-/.年]\d{1,2}")),
    "delivery_date": ("交期", re.compile(r"(?:交期|交貨|到貨).{0,30}(?:19|20)?\d")),
    "quantity": ("數量", re.compile(r"(?:數量|共計|合計).{0,20}\d")),
    "status": ("狀態", re.compile(r"(?:狀態|進度|已完成|處理中|待)")),
    "steps": ("步驟", re.compile(r"(?:步驟|Step\s*\d|首先|接著)", re.I)),
    "procedure": ("流程", re.compile(r"(?:流程|步驟|完成條件|Step\s*\d)", re.I)),
    "actor": ("負責人／角色", re.compile(r"(?:負責|承辦|操作人|角色)")),
    "revision": ("版本", re.compile(r"(?:版本|版次|revision|rev\.?\s*\d)", re.I)),
}


def legacy_coverage_to_evidence_decision(
    legacy: Mapping[str, Any],
    *,
    execution_status: ExecutionStatus | str = ExecutionStatus.OK,
) -> dict[str, Any]:
    """Adapt the legacy response without giving it new decision authority."""
    status = ExecutionStatus(execution_status)
    covered = [str(value) for value in legacy.get("covered_slots") or []]
    missing = [str(value) for value in legacy.get("missing_slots") or []]
    legacy_decision = str(legacy.get("decision") or "abstain")
    if status is not ExecutionStatus.OK:
        state = EvidenceState.PARTIAL if covered else EvidenceState.INSUFFICIENT_CONTEXT
        action = ResponseAction.ESCALATE
    elif legacy_decision == "answer":
        state, action = EvidenceState.COMPLETE, ResponseAction.ANSWER
    elif legacy_decision == "partial":
        state, action = EvidenceState.PARTIAL, ResponseAction.ANSWER_PARTIAL
    else:
        state, action = EvidenceState.ABSENT, ResponseAction.ABSTAIN
    return {
        **dict(legacy),
        "schema_version": "legacy-coverage-adapter.v1",
        "legacy_decision": legacy_decision,
        "evidence_state": state.value,
        "response_action": action.value,
        "execution_status": status.value,
        "answered_requirements": covered,
        "missing_requirements": [
            {
                "requirement_id": slot_id,
                "label": slot_id,
                "reason_codes": [str(legacy.get("reason") or "legacy_coverage_missing")],
                "required": True,
            }
            for slot_id in missing
        ],
        "reviewed_scope": {},
        "conflicts": [],
    }


def assess_retrieval_coverage(query_plan: Mapping[str, Any], results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    requested = [str(slot) for slot in (query_plan.get("requested_slots") or [])]
    structured_slots = {"unit_price", "total_price", "amount", "date", "delivery_date", "quantity", "status", "revision"}
    metadata = [result.get("metadata") or {} for result in results]
    if set(requested) & structured_slots and any(item.get("evidence_kind") == "structured_ambiguity" for item in metadata):
        return {
            "decision": "abstain",
            "covered_slots": [],
            "missing_slots": requested,
            "missing_labels": [SLOT_RULES.get(slot, (slot,))[0] for slot in requested],
            "reason": "structured_row_identity_ambiguous",
            "risk_class": str(query_plan.get("risk_class") or "normal"),
        }
    corpus = "\n".join(str(result.get("content") or "") for result in results)
    covered: list[str] = []
    missing: list[str] = []
    for slot in requested:
        rule = SLOT_RULES.get(slot)
        if rule and rule[1].search(corpus):
            covered.append(slot)
        else:
            missing.append(slot)

    risk_class = str(query_plan.get("risk_class") or "normal")
    incomplete_procedure = any(
        item.get("evidence_kind") == "procedure" and item.get("procedure_status") != "complete"
        for item in metadata
    )
    ambiguous_procedure = any(item.get("evidence_kind") == "procedure_ambiguity" for item in metadata)
    if ambiguous_procedure and set(requested) & {"steps", "procedure", "actor"}:
        return {
            "decision": "abstain", "covered_slots": [], "missing_slots": requested,
            "missing_labels": [SLOT_RULES.get(slot, (slot,))[0] for slot in requested],
            "reason": "procedure_identity_ambiguous", "risk_class": risk_class,
        }
    if incomplete_procedure and set(requested) & {"steps", "procedure", "actor"}:
        return {
            "decision": "abstain" if risk_class == "safety_critical" else "partial",
            "covered_slots": covered,
            "missing_slots": list(dict.fromkeys([*missing, *requested])),
            "missing_labels": [SLOT_RULES.get(slot, (slot,))[0] for slot in requested],
            "reason": "procedure_branch_context_missing",
            "risk_class": risk_class,
        }
    if risk_class == "safety_critical":
        authoritative = any(
            int((result.get("metadata") or {}).get("authority_level") or 0) >= 90
            for result in results
        )
        if not authoritative:
            return {"decision": "abstain", "covered_slots": [], "missing_slots": requested,
                    "reason": "safety_requires_approved_authority", "risk_class": risk_class}
    if missing and covered:
        decision = "partial"
    elif missing or (requested and not results):
        decision = "abstain"
    elif results:
        decision = "answer"
    else:
        decision = "abstain"
    return {"decision": decision, "covered_slots": covered, "missing_slots": missing,
            "missing_labels": [SLOT_RULES.get(slot, (slot,))[0] for slot in missing],
            "reason": "slot_coverage", "risk_class": risk_class}
