from datetime import datetime, timedelta, timezone
import hashlib
import os
import subprocess
import sys
import uuid

import pytest

from app.gateway.citation import CitationBuilder
from app.services.authority_policy import AuthorityEvidence, AuthorityPolicy
from app.services.document_profile import build_document_profile
from app.services.evidence_contract import AnswerSlot, EvidenceContract, EvidenceItem
from app.services.knowledge_unit import KnowledgeUnit
from app.services.procedure_resolver import ProcedureStep, resolve_procedure
from app.services.structured_record_resolver import Record, StructuredRecordResolver
from app.services.evidence_orchestrator import decide_evidence
from app.services.source_verifier import deterministic_claim_validation
from app.services.retrieval_coverage import assess_retrieval_coverage


def test_opaque_citation_revision_is_stable_and_not_runtime_hash():
    value = "sharepoint-etag:abc/中文"
    expected = (int.from_bytes(hashlib.sha256(value.encode()).digest()[:4], "big") % 2_000_000_000) + 1
    assert CitationBuilder._coerce_revision(value) == expected


def test_opaque_citation_revision_is_stable_across_processes():
    code = "from app.gateway.citation import CitationBuilder;print(CitationBuilder._coerce_revision('opaque:中文:v7'))"
    env1 = {**os.environ, "PYTHONHASHSEED": "1"}
    env2 = {**os.environ, "PYTHONHASHSEED": "random"}
    a = subprocess.check_output([sys.executable, "-c", code], text=True, env=env1).strip()
    b = subprocess.check_output([sys.executable, "-c", code], text=True, env=env2).strip()
    assert a == b


def test_document_completed_is_not_automatically_answer_ready():
    p = build_document_profile(file_type="pdf", text="少量文字", parse_engine="text_fallback", ocr_used=True)
    assert p.answer_ready is False
    assert any(w["code"] == "scan_without_verified_ocr" for w in p.warnings)


def test_supported_table_readiness_is_capability_specific():
    p = build_document_profile(file_type="csv", text="客戶,單價\n甲,120")
    assert p.answer_ready and p.readiness["structured_rows"]
    assert not p.readiness["compiled"]


def test_knowledge_unit_rejects_wrong_hash():
    with pytest.raises(ValueError):
        KnowledgeUnit("t", "d", "1", "u", "chunk", "body", "bad")


def _e(slot="price", entity="customer:a", active=True, acl=True):
    return EvidenceItem(slot, 120, "money", "doc", "1", "row:1:price", "field", "單價 120 元",
                        entity_id=entity, acl_verified=acl, active_revision=active)


def test_evidence_contract_never_silently_fills_missing_slot():
    contract = EvidenceContract([AnswerSlot("price", "單價", "money", entity_binding="customer:a"), AnswerSlot("lead", "交期", "date")])
    result = contract.decision([_e()])
    assert result["decision"] == "partial"
    assert result["missing_slots"] == ["lead"]


def test_evidence_contract_rejects_cross_entity_and_inactive_revision():
    contract = EvidenceContract([AnswerSlot("price", "單價", "money", entity_binding="customer:a")])
    assert contract.decision([_e(entity="customer:b")])["decision"] == "abstain"
    assert contract.decision([_e(active=False)])["decision"] == "abstain"


def test_structured_resolver_keeps_values_on_one_row():
    rows = [Record("r1", {"customer": "A"}, {"price": "100", "date": "2026-08-01"}, {"row": 1}),
            Record("r2", {"customer": "B"}, {"price": "200", "date": "2026-09-01"}, {"row": 2})]
    result = StructuredRecordResolver().resolve(rows, identity={"customer": "A"}, fields=["price", "date"])
    assert result.status == "complete"
    assert {v["row_id"] for v in result.values} == {"r1"}


def test_aggregate_retains_exact_input_rows():
    rows = [Record("r1", {"id": "1"}, {"amount": "1,200"}, {}), Record("r2", {"id": "2"}, {"amount": "300"}, {})]
    result = StructuredRecordResolver().aggregate(rows, field="amount", operation="sum")
    assert result.calculation == {"operation": "sum", "field": "amount", "input_row_ids": ["r1", "r2"], "input_values": ["1200", "300"], "result": "1500"}


def test_procedure_selects_only_matching_branch_and_reports_missing():
    steps = [ProcedureStep("start", 1, "關機"), ProcedureStep("hot", 2, "等待降溫", conditions={"temperature": "high"}),
             ProcedureStep("cold", 2, "直接檢查", conditions={"temperature": "low"})]
    result = resolve_procedure(steps, {"temperature": "high"}, ["start", "hot", "finish"])
    assert [s.key for s in result.steps] == ["start", "hot"]
    assert result.status == "partial" and result.missing_phases == ["finish"]


def test_authority_excludes_draft_expired_and_wrong_scope():
    now = datetime.now(timezone.utc)
    items = [AuthorityEvidence("draft", "approved_knowhow", "x", {}, approved=False),
             AuthorityEvidence("old", "primary_document", "x", {}, effective_to=now-timedelta(seconds=1)),
             AuthorityEvidence("other", "primary_document", "x", {}, scope={"plant": "B"}),
             AuthorityEvidence("ok", "primary_document", "y", {}, scope={"plant": "A"})]
    result = AuthorityPolicy().rank(items, context={"plant": "A"}, at=now)
    assert [x.evidence_id for x in result["usable"]] == ["ok"]
    assert {x["reason"] for x in result["excluded"]} == {"not_approved", "expired", "scope_mismatch"}


def test_deterministic_validator_blocks_unsupported_number_and_date():
    result = deterministic_claim_validation("單價 130 元，交期 2026-09-01", ["單價 120 元，交期 2026-08-01"])
    assert result["verified"] is False
    assert {x["value"] for x in result["unsupported"]} >= {"130 元", "2026-09-01"}


def test_evidence_orchestrator_uses_structured_tier():
    contract = EvidenceContract([AnswerSlot("price", "單價", "money", entity_binding="customer:a")])
    item = _e()
    decision = decide_evidence(contract, [item])
    assert decision.tier == 1 and decision.action == "answer"


def test_retrieval_coverage_never_silently_fills_missing_requested_slot():
    result = assess_retrieval_coverage(
        {"requested_slots": ["unit_price", "delivery_date"], "risk_class": "normal"},
        [{"content": "設備 P-200 單價為 120 元"}],
    )
    assert result["decision"] == "partial"
    assert result["covered_slots"] == ["unit_price"]
    assert result["missing_slots"] == ["delivery_date"]


def test_safety_critical_retrieval_requires_approved_authority():
    result = assess_retrieval_coverage(
        {"requested_slots": ["steps"], "risk_class": "safety_critical"},
        [{"content": "步驟 1：停機", "metadata": {"authority_level": 60}}],
    )
    assert result["decision"] == "abstain"
    assert result["reason"] == "safety_requires_approved_authority"


def test_query_plan_routes_slots_to_canonical_projection_arms():
    from app.services.query_plan import build_query_plan
    from app.services.tool_router import arms_for_plan

    structured = arms_for_plan(build_query_plan("C-01 的單價與交期日期？"))
    procedure = arms_for_plan(build_query_plan("安全停機流程有哪些步驟？"))
    assert structured[:2] == ["structured", "chunk"]
    assert procedure[0] == "procedure" and "chunk" in procedure


def test_canonical_projection_ambiguity_overrides_narrative_values():
    result = assess_retrieval_coverage(
        {"requested_slots": ["unit_price"], "risk_class": "normal"},
        [
            {"content": "單價 120 元"},
            {"content": "資料列不唯一", "metadata": {"evidence_kind": "structured_ambiguity"}},
        ],
    )
    assert result["decision"] == "abstain"
    assert result["reason"] == "structured_row_identity_ambiguous"


def test_incomplete_safety_procedure_is_never_answerable():
    result = assess_retrieval_coverage(
        {"requested_slots": ["steps"], "risk_class": "safety_critical"},
        [{"content": "步驟 1：停機", "metadata": {
            "evidence_kind": "procedure", "procedure_status": "partial", "authority_level": 100,
        }}],
    )
    assert result["decision"] == "abstain"
    assert result["reason"] == "procedure_branch_context_missing"


def test_knowhow_scope_requires_role_and_named_equipment():
    from types import SimpleNamespace
    from app.packs.mka.knowledge_provider import ApprovedKnowhowProvider
    from app.platform.knowledge import KnowledgeContributionContext

    card = SimpleNamespace(
        applicable_roles=["master"],
        equipment_ids=["P-200"],
        product_ids=[],
        customer_ids=[],
        authority_level=90,
        risk_level="medium",
    )
    master = SimpleNamespace(role_ids=["master"])
    sales = SimpleNamespace(role_ids=["sales"])

    def context(authz, query):
        return KnowledgeContributionContext(authz=authz, query=query, db=None)

    assert ApprovedKnowhowProvider._applies(
        card, context=context(master, "P-200 如何校正")
    )
    assert not ApprovedKnowhowProvider._applies(
        card, context=context(master, "如何校正")
    )
    assert not ApprovedKnowhowProvider._applies(
        card, context=context(sales, "P-200 如何校正")
    )


def test_high_risk_knowhow_requires_formal_authority():
    from types import SimpleNamespace
    from app.packs.mka.knowledge_provider import ApprovedKnowhowProvider
    from app.platform.knowledge import KnowledgeContributionContext

    card = SimpleNamespace(
        applicable_roles=[], equipment_ids=[], product_ids=[], customer_ids=[],
        authority_level=60, risk_level="high",
    )
    authz = SimpleNamespace(role_ids=["master"])
    assert not ApprovedKnowhowProvider._applies(
        card,
        context=KnowledgeContributionContext(
            authz=authz, query="安全停機步驟", db=None
        ),
    )


def test_persistent_lexical_index_is_incremental_and_searchable(test_engine):
    import app.models  # noqa: F401
    from sqlalchemy.orm import sessionmaker
    from app.db.base_class import Base
    from app.models.document import Document, DocumentChunk
    from app.models.tenant import Tenant
    from app.models.knowledge_engine import LexicalIndexEntry
    from app.services.lexical_index import search, upsert_chunks

    Base.metadata.create_all(bind=test_engine)
    db = sessionmaker(bind=test_engine)()
    try:
        tenant = Tenant(id=uuid.uuid4(), name=f"Lexical-{uuid.uuid4().hex[:8]}", plan="free", status="active")
        db.add(tenant); db.flush()
        doc = Document(tenant_id=tenant.id, filename="設備規範.txt", file_type="txt", status="completed", version=1)
        db.add(doc); db.flush()
        chunks = [DocumentChunk(tenant_id=tenant.id, document_id=doc.id, chunk_index=0, text="P-200 主軸安全檢查", chunk_hash=uuid.uuid4().hex),
                  DocumentChunk(tenant_id=tenant.id, document_id=doc.id, chunk_index=1, text="一般保養紀錄", chunk_hash=uuid.uuid4().hex)]
        db.add_all(chunks); db.flush()
        assert upsert_chunks(db, chunks, doc) == 2
        assert upsert_chunks(db, chunks, doc) == 2
        assert db.query(LexicalIndexEntry).filter(LexicalIndexEntry.tenant_id == tenant.id).count() == 2
        base = db.query(DocumentChunk).join(Document, DocumentChunk.document_id == Document.id)
        found = search(db, tenant_id=tenant.id, query="主軸安全", top_k=5, base_query=base)
        assert found and found[0][0].id == chunks[0].id
    finally:
        db.rollback(); db.close()


def test_process_read_only_barrier_blocks_writes(test_engine):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError
    from app.services.read_only_barrier import process_read_only
    with process_read_only(test_engine):
        with test_engine.connect() as conn:
            with pytest.raises(DBAPIError):
                conn.execute(text("CREATE TEMP TABLE should_not_write(id integer)"))
