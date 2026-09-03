from __future__ import annotations

import pytest

from app.services.answer_plan import (
    ConstrainedParaphrase,
    build_answer_plan,
    render_answer_plan,
    render_constrained_or_fallback,
)
from app.services.evidence_contract import (
    AnswerRequirement,
    EvidenceContract,
    EvidenceItem,
    ExecutionStatus,
    ReviewedScope,
)
from app.services.evidence_orchestrator import decide_evidence
from app.services.source_verifier import validate_answer_plan_claims


def _item(
    slot: str,
    value,
    *,
    value_type: str = "text",
    unit: str = "unit-1",
    entity: str | None = None,
    derivation: str = "direct",
    closed: bool = False,
) -> EvidenceItem:
    return EvidenceItem(
        slot_id=slot,
        value=value,
        value_type=value_type,
        document_id="doc-1",
        document_revision="7",
        unit_id=unit,
        unit_type="fact",
        quote=str(value),
        entity_id=entity,
        kb_revision_id="kb-rev-7",
        locator={"page": 3, "section": "Rules"},
        acl_verified=True,
        active_revision=True,
        tenant_id="tenant-1",
        knowledge_release_id="release-7",
        release_active=True,
        quality_ready=True,
        derivation=derivation,
        closed_scope_verified=closed,
        evidence_id=f"evidence-{unit}",
    )


def _decision(
    slots,
    evidence,
    *,
    status: ExecutionStatus = ExecutionStatus.OK,
    answer_type: str = "scalar",
):
    contract = EvidenceContract(
        list(slots),
        reviewed_scope=ReviewedScope(
            tenant_id="tenant-1",
            kb_revision_id="kb-rev-7",
            knowledge_release_id="release-7",
            exhaustive=answer_type == "set",
        ),
    )
    decision = decide_evidence(
        contract,
        list(evidence),
        query_spec={"answer_type": answer_type},
        execution_status=status,
    )
    return decision, build_answer_plan(
        decision,
        query_spec={"answer_type": answer_type},
    )


def test_judgment_starts_with_direct_answer_then_conditions():
    decision, plan = _decision(
        (
            AnswerRequirement("answer", "是否允許", value_type="boolean"),
            AnswerRequirement("condition", "必要條件"),
        ),
        (
            _item("answer", False, value_type="boolean", unit="answer"),
            _item("condition", "主管核准後才可例外", unit="condition"),
        ),
        answer_type="judgment",
    )
    assert decision.evidence_state == "complete"
    rendered = render_answer_plan(plan)
    assert rendered.text.startswith("否。")
    assert "主管核准後才可例外" in rendered.text
    assert len(rendered.claim_ids) == 2


def test_partial_set_names_missing_item_and_never_claims_completeness():
    _, plan = _decision(
        (
            AnswerRequirement(
                "member-a",
                "成員 A",
                value_type="text",
            ),
            AnswerRequirement("member-b", "成員 B", value_type="text"),
        ),
        (_item("member-a", "A", unit="a"),),
        answer_type="set",
    )
    assert plan.evidence_state == "partial"
    assert plan.answer_type == "partial_gap"
    rendered = render_answer_plan(plan)
    assert "已確認項目" in rendered.text
    assert "尚缺項目：成員 B" in rendered.text


@pytest.mark.parametrize(
    ("answer_type", "values", "label"),
    (
        ("procedure", ("先停機", "再上鎖"), "執行順序"),
        ("comparison", ("A：10", "B：12"), "比較結果"),
        ("formula", ("10 × 2 = 20",), "計算依據"),
        ("definition", ("AX 是核准代碼",), "來源版本"),
        ("scalar", ("AX-17",), "來源版本"),
    ),
)
def test_deterministic_renderer_covers_answer_shapes(answer_type, values, label):
    slots = []
    items = []
    for index, value in enumerate(values):
        slot = f"slot-{index}"
        slots.append(AnswerRequirement(slot, slot))
        items.append(_item(slot, value, unit=slot))
    _, plan = _decision(slots, items, answer_type=answer_type)
    first = render_answer_plan(plan)
    second = render_answer_plan(plan)
    assert first == second
    assert label in first.text
    if answer_type == "procedure":
        assert first.text.index("1. 先停機") < first.text.index("2. 再上鎖")


def test_absent_clarify_conflict_and_execution_failure_are_distinct():
    slot = AnswerRequirement("answer", "核准代碼")
    absent_decision = decide_evidence(
        EvidenceContract(
            (slot,),
            reviewed_scope=ReviewedScope(tenant_id="tenant-1", exhaustive=True),
        ),
        (),
    )
    absent = build_answer_plan(absent_decision)
    assert absent.evidence_state == "absent"
    assert "未找到可驗證依據" in render_answer_plan(absent).text

    unclear_contract = EvidenceContract(
        (slot,), reviewed_scope=ReviewedScope(tenant_id="tenant-1")
    )
    unclear_decision = decide_evidence(
        unclear_contract,
        (),
        query_spec={"ambiguity": ["entity"], "answer_type": "scalar"},
    )
    unclear = build_answer_plan(unclear_decision)
    assert unclear.evidence_state == "insufficient_context"

    conflict_contract = EvidenceContract((slot,))
    conflict_decision = decide_evidence(
        conflict_contract,
        (
            _item("answer", "AX-17", unit="one"),
            EvidenceItem(
                **{
                    **_item("answer", "AX-18", unit="two").__dict__,
                    "conflict_key": "approval-code",
                }
            ),
            EvidenceItem(
                **{
                    **_item("answer", "AX-17", unit="one").__dict__,
                    "conflict_key": "approval-code",
                }
            ),
        ),
    )
    conflict = build_answer_plan(conflict_decision)
    assert conflict.evidence_state == "conflict"
    assert "未能消解" in render_answer_plan(conflict).text

    _, failed = _decision(
        (slot,),
        (_item("answer", "AX-17"),),
        status=ExecutionStatus.TIMEOUT,
    )
    failed_text = render_answer_plan(failed).text
    assert "系統未完成" in failed_text
    assert "未找到" not in failed_text


def test_constrained_paraphrase_rejects_claim_literal_entity_and_scope_escape():
    _, plan = _decision(
        (AnswerRequirement("answer", "核准代碼", value_type="code"),),
        (
            _item(
                "answer",
                "AX-17",
                value_type="code",
                entity="machine-a",
            ),
        ),
    )
    claim_id = plan.claims[0].claim_id
    valid = validate_answer_plan_claims(
        plan,
        answer="核准代碼是 AX-17。",
        claim_ids=(claim_id,),
        entity_mentions=("machine-a",),
        scope_claims={"tenant_id": "tenant-1"},
    )
    assert valid["verified"] is True

    invalid = ConstrainedParaphrase(
        text="王小明核准代碼是 AX-99，期限 2030/01/01。",
        claim_ids=(claim_id, "claim:invented"),
        entity_mentions=("王小明",),
        scope_claims={"tenant_id": "tenant-2"},
    )
    verification = validate_answer_plan_claims(
        plan,
        answer=invalid.text,
        claim_ids=invalid.claim_ids,
        entity_mentions=invalid.entity_mentions,
        scope_claims=invalid.scope_claims,
    )
    assert verification["verified"] is False
    assert verification["unknown_claim_ids"] == ["claim:invented"]
    assert {item["type"] for item in verification["unsupported_literals"]} >= {
        "numeric",
        "date",
        "code",
    }
    assert verification["unsupported_entities"] == ["王小明"]
    assert verification["unsupported_scope"] == {"tenant_id": "tenant-2"}
    assert render_constrained_or_fallback(plan, invalid) == render_answer_plan(plan)


@pytest.mark.asyncio
async def test_sync_and_stream_use_the_same_verified_render(monkeypatch):
    from app.config import settings
    from app.services.chat_orchestrator import ChatOrchestrator

    _, plan = _decision(
        (AnswerRequirement("answer", "核准代碼", value_type="code"),),
        (_item("answer", "AX-17", value_type="code"),),
    )
    rendered = render_answer_plan(plan)
    context = {
        "request_id": "request-1",
        "has_policy": True,
        "company_policy_raw": {"content": "AX-17"},
        "sources": [],
        "context_parts": ["AX-17"],
        "retrieval": {},
        "disclaimer": "test",
        "answer_plan": plan.to_dict(),
        "deterministic_answer": rendered.to_dict(),
    }
    orchestrator = ChatOrchestrator.__new__(ChatOrchestrator)
    orchestrator._openai = None
    orchestrator._openai_async = None

    async def retrieve_context(**_kwargs):
        return dict(context)

    orchestrator.retrieve_context = retrieve_context
    monkeypatch.setattr(settings, "HR_COMPATIBILITY_PACK_ENABLED", False)
    sync = await orchestrator.process_query(
        tenant_id="00000000-0000-0000-0000-000000000001",
        question="代碼？",
        authz=object(),
    )
    streamed = []
    async for piece in orchestrator.stream_answer("代碼？", dict(context)):
        streamed.append(piece)
    assert sync["answer"] == "".join(streamed) == rendered.text
    assert sync["decision"] == plan.to_dict()
