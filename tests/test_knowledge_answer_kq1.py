from datetime import datetime, timezone

import pytest

from app.services.evidence_contract import (
    AnswerRequirement,
    EvidenceContract,
    EvidenceItem,
    ExecutionStatus,
    ReviewedScope,
    redact_trace_payload,
)
from app.services.query_plan import build_query_plan
from app.services.retrieval_coverage import legacy_coverage_to_evidence_decision


def _item(**changes):
    values = {
        "slot_id": "price",
        "value": 120,
        "value_type": "money",
        "document_id": "doc-a",
        "document_revision": "7",
        "unit_id": "unit-a",
        "unit_type": "field",
        "quote": "單價 120 元",
        "entity_id": "product:P-200",
        "authority_class": "approved_sop",
        "kb_revision_id": "kb-r7",
        "acl_verified": True,
        "active_revision": True,
        "tenant_id": "tenant-a",
        "department_id": "plant-a",
        "source_id": "source-a",
        "knowledge_release_id": "release-a",
        "effective_from": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "effective_to": datetime(2027, 1, 1, tzinfo=timezone.utc),
        "relation_kinds": ("same_record",),
        "closed_scope_verified": True,
    }
    values.update(changes)
    return EvidenceItem(**values)


def _requirement(**changes):
    values = {
        "slot_id": "price",
        "label": "單價",
        "value_type": "money",
        "entity_binding": "product:P-200",
        "source_scope": {
            "tenant_id": "tenant-a",
            "department_id": "plant-a",
            "source_id": "source-a",
            "kb_revision_id": "kb-r7",
            "document_revision": "7",
            "knowledge_release_id": "release-a",
        },
        "authority_requirement": ["approved_sop"],
        "temporal_requirement": {"valid_on": "2026-09-03T00:00:00Z", "required": True},
        "required_relations": ["same_record"],
    }
    values.update(changes)
    return AnswerRequirement(**values)


def test_query_spec_v2_preserves_dates_numbers_negation_codes_and_sources():
    question = "不要使用舊版；根據《設備手冊.pdf》，P-200 在 2026-09-03 的單價 120 元？"
    plan = build_query_plan(question)
    assert plan.plan_version == "2.0"
    assert plan.query_id and plan.original_question == question
    assert plan.requested_facets == plan.requested_slots == ["unit_price"]
    assert plan.source_scope == {"document_names": ["設備手冊.pdf"]}
    assert "2026-09-03" in plan.preserved_tokens["dates"]
    assert "120 元" in plan.preserved_tokens["numbers"]
    assert "不要" in plan.preserved_tokens["negations"]
    assert "P-200" in plan.preserved_tokens["codes"]
    assert plan.validate_preservation() == []


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"value": "120"}, "value_type_mismatch"),
        ({"entity_id": "product:P-201"}, "entity_binding_mismatch"),
        ({"tenant_id": "tenant-b"}, "source_scope_or_acl_missing"),
        ({"department_id": "plant-b"}, "source_scope_or_acl_missing"),
        ({"source_id": "source-b"}, "source_scope_or_acl_missing"),
        ({"kb_revision_id": "kb-r6"}, "source_scope_or_acl_missing"),
        ({"document_revision": "6"}, "source_scope_or_acl_missing"),
        ({"active_revision": False}, "inactive_or_wrong_revision"),
        ({"authority_class": "draft"}, "authority_not_allowed"),
        ({"effective_to": datetime(2026, 9, 3, tzinfo=timezone.utc)}, "temporal_requirement_not_met"),
        ({"relation_kinds": ()}, "relation_closure_missing"),
    ],
)
def test_full_contract_rejects_invalid_evidence(changes, reason):
    result = EvidenceContract([_requirement()]).decision([_item(**changes)])
    assert result["decision"] == "abstain"
    assert reason in result["coverage"][0]["reasons"]


def test_contract_accepts_exact_scope_type_time_authority_and_relation():
    result = EvidenceContract([_requirement()]).decision([_item()])
    assert result["evidence_state"] == "complete"
    assert result["response_action"] == "answer"
    assert result["execution_status"] == "ok"
    assert result["answered_requirements"] == ["price"]


def test_exact_cardinality_and_closed_list_require_reviewed_scope_proof():
    requirement = _requirement(
        minimum_values=2,
        expected_cardinality=2,
        exhaustive=True,
    )
    two = [_item(unit_id="u1"), _item(unit_id="u2")]
    not_reviewed = EvidenceContract([requirement]).decision(two)
    assert "closed_scope_not_verified" in not_reviewed["coverage"][0]["reasons"]
    reviewed = EvidenceContract(
        [requirement], reviewed_scope=ReviewedScope(tenant_id="tenant-a", exhaustive=True)
    ).decision(two)
    assert reviewed["decision"] == "answer"
    extra = reviewed = EvidenceContract(
        [requirement], reviewed_scope=ReviewedScope(tenant_id="tenant-a", exhaustive=True)
    ).decision([*two, _item(unit_id="u3")])
    assert extra["decision"] == "abstain"
    assert "expected_cardinality_mismatch" in extra["coverage"][0]["reasons"]


@pytest.mark.parametrize(
    "status",
    [
        ExecutionStatus.PROVIDER_ERROR,
        ExecutionStatus.SCHEMA_ERROR,
        ExecutionStatus.TIMEOUT,
        ExecutionStatus.PACK_FAILURE,
        ExecutionStatus.INTERNAL_ERROR,
    ],
)
def test_execution_failure_is_never_misrepresented_as_absent(status):
    result = EvidenceContract([_requirement()]).decision([], execution_status=status)
    assert result["decision"] == "error"
    assert result["execution_status"] == status.value
    assert result["evidence_state"] != "absent"
    assert result["response_action"] == "escalate"


def test_legacy_adapter_preserves_shape_and_separates_execution_failure():
    legacy = {
        "decision": "abstain",
        "covered_slots": [],
        "missing_slots": ["price"],
        "reason": "slot_coverage",
        "risk_class": "normal",
    }
    compatible = legacy_coverage_to_evidence_decision(legacy)
    assert compatible["decision"] == "abstain"
    assert compatible["evidence_state"] == "absent"
    failed = legacy_coverage_to_evidence_decision(
        legacy, execution_status=ExecutionStatus.TIMEOUT
    )
    assert failed["legacy_decision"] == "abstain"
    assert failed["execution_status"] == "timeout"
    assert failed["evidence_state"] == "insufficient_context"
    assert failed["response_action"] == "escalate"


def test_trace_redaction_keeps_hashes_but_removes_secret_text():
    trace = redact_trace_payload(
        {"token": "secret-token", "nested": {"quote": "private source"}, "latency_ms": 7}
    )
    rendered = str(trace)
    assert "secret-token" not in rendered
    assert "private source" not in rendered
    assert trace["latency_ms"] == 7
    assert trace["token"]["redacted"] is True
