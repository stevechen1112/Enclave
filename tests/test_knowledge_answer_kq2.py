from datetime import datetime, timezone

from app.services.evidence_contract import (
    AnswerRequirement,
    EvidenceContract,
    EvidenceItem,
    ExecutionStatus,
    ReviewedScope,
)
from app.services.evidence_orchestrator import decide_evidence


def _item(slot="answer", value="yes", **changes):
    values = {
        "slot_id": slot,
        "value": value,
        "value_type": "text",
        "document_id": "doc-a",
        "document_revision": "2",
        "unit_id": f"unit-{slot}-{value}",
        "unit_type": "narrative",
        "quote": f"{slot}: {value}",
        "entity_id": "machine:P-200",
        "authority_class": "approved_sop",
        "kb_revision_id": "kb-r2",
        "acl_verified": True,
        "active_revision": True,
        "tenant_id": "tenant-a",
        "department_id": "plant-a",
        "knowledge_release_id": "release-a",
        "evidence_id": f"e-{slot}-{value}",
    }
    values.update(changes)
    return EvidenceItem(**values)


def _contract(*requirements, exhaustive=False):
    return EvidenceContract(
        list(requirements or [AnswerRequirement("answer", "答案")]),
        reviewed_scope=ReviewedScope(
            tenant_id="tenant-a",
            kb_revision_id="kb-r2",
            knowledge_release_id="release-a",
            exhaustive=exhaustive,
        ),
    )


def test_complete_partial_absent_and_insufficient_context_are_distinct():
    answer = AnswerRequirement("answer", "答案")
    detail = AnswerRequirement("detail", "細節")
    complete = decide_evidence(_contract(answer), [_item()])
    assert (complete.evidence_state, complete.response_action) == ("complete", "answer")
    partial = decide_evidence(_contract(answer, detail), [_item()])
    assert (partial.evidence_state, partial.response_action) == (
        "partial",
        "answer_partial",
    )
    absent = decide_evidence(_contract(answer, exhaustive=True), [])
    assert (absent.evidence_state, absent.response_action) == ("absent", "abstain")
    unclear = decide_evidence(_contract(answer, exhaustive=False), [])
    assert (unclear.evidence_state, unclear.response_action) == (
        "insufficient_context",
        "clarify",
    )


def test_near_evidence_never_becomes_verified_claim():
    decision = decide_evidence(
        _contract(AnswerRequirement("answer", "答案")),
        [_item(slot="neighbor", value="adjacent topic")],
    )
    assert decision.verified_claims == []
    assert [item.slot_id for item in decision.near_evidence] == ["neighbor"]


def test_acl_revision_deny_and_tombstone_are_rechecked_before_claim_admission():
    for item in (
        _item(acl_verified=False),
        _item(active_revision=False),
        _item(denied=True),
        _item(tombstoned=True),
        _item(release_active=False),
        _item(quality_ready=False),
    ):
        decision = decide_evidence(_contract(exhaustive=True), [item])
        assert decision.verified_claims == []
        assert decision.near_evidence == [item]


def test_conflict_requires_same_matter_entity_scope_and_overlapping_time():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2027, 1, 1, tzinfo=timezone.utc)
    left = _item(
        value="enabled",
        conflict_key="machine-mode",
        effective_from=start,
        effective_to=end,
    )
    right = _item(
        value="disabled",
        conflict_key="machine-mode",
        effective_from=start,
        effective_to=end,
    )
    conflict = decide_evidence(_contract(), [left, right])
    assert conflict.evidence_state == "conflict"
    assert conflict.response_action == "escalate"
    assert len(conflict.conflicts) == 1

    other_scope = _item(
        value="disabled",
        conflict_key="machine-mode",
        department_id="plant-b",
        effective_from=start,
        effective_to=end,
    )
    not_conflict = decide_evidence(_contract(), [left, other_scope])
    assert not_conflict.evidence_state == "complete"


def test_non_overlapping_revisions_are_not_a_conflict():
    old = _item(
        value="old",
        conflict_key="policy",
        effective_from=datetime(2025, 1, 1, tzinfo=timezone.utc),
        effective_to=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    new = _item(
        value="new",
        conflict_key="policy",
        effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    decision = decide_evidence(_contract(), [old, new])
    assert decision.evidence_state == "complete"
    assert decision.conflicts == []


def test_aggregate_requires_registered_deterministic_derivation():
    requirement = AnswerRequirement(
        "answer", "總計", allowed_derivation=["direct", "sum"]
    )
    unsafe = decide_evidence(_contract(requirement), [_item()], operation="aggregate")
    assert unsafe.action == "abstain"
    safe = decide_evidence(
        _contract(requirement), [_item(derivation="sum")], operation="aggregate"
    )
    assert safe.action == "answer" and safe.tier == 0


def test_execution_failure_is_not_counted_as_safe_absence():
    decision = decide_evidence(
        _contract(exhaustive=True),
        [],
        execution_status=ExecutionStatus.PROVIDER_ERROR,
    )
    assert decision.action == "error"
    assert decision.execution_status == "provider_error"
    assert decision.evidence_state != "absent"
    assert decision.verified_claims == []


def test_six_stage_trace_and_decision_hash_are_deterministic_and_minimized():
    kwargs = {
        "query_spec": {"plan_version": "2.0", "ambiguity": []},
        "pack_versions": {"manufacturing": "1.0.0"},
    }
    first = decide_evidence(_contract(), [_item()], **kwargs)
    second = decide_evidence(_contract(), [_item()], **kwargs)
    assert first.decision_hash == second.decision_hash
    assert [row["stage"] for row in first.stage_trace] == [
        "parse",
        "retrieve",
        "select",
        "applicability",
        "completeness",
        "conversation",
    ]
    serialized = str(first.to_dict())
    assert "answer: yes" not in serialized
    assert first.kb_revision_id == "kb-r2"
    assert first.knowledge_release_id == "release-a"
