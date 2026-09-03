from __future__ import annotations

import ast
import importlib
from dataclasses import fields
from pathlib import Path

from app.packs.hr_knowledge.manifest import build_knowledge_contribution as build_hr
from app.packs.manufacturing_knowledge.manifest import (
    build_knowledge_contribution as build_manufacturing,
)
from app.platform.packs.knowledge import (
    KnowledgePackRuntime,
    PackCandidate,
    admit_pack_candidates,
)
from app.services.evidence_contract import (
    AnswerSlot,
    EvidenceContract,
    EvidenceItem,
    ExecutionStatus,
    ReviewedScope,
)
from app.services.evidence_orchestrator import EvidenceDecision, decide_evidence

ROOT = Path(__file__).parents[1]


def _candidate(pack: str, tenant: str, *, risk: str = "normal") -> PackCandidate:
    return PackCandidate(
        pack_key=pack,
        tenant_id=tenant,
        requirement_id="r1",
        unit_revision_id="ur1",
        evidence_span_id="span1",
        source_revision_id="sr1",
        artifact_id="a1",
        risk=risk,
    )


def _evidence(tenant: str, authority: str = "primary_document") -> EvidenceItem:
    return EvidenceItem(
        slot_id="r1",
        value="verified",
        value_type="text",
        document_id="d1",
        document_revision="sr1",
        unit_id="ur1",
        unit_type="policy",
        quote="source text",
        tenant_id=tenant,
        authority_class=authority,
        evidence_id="span1",
        acl_verified=True,
        active_revision=True,
        release_active=True,
        quality_ready=True,
    )


def _contract(tenant: str) -> EvidenceContract:
    return EvidenceContract(
        slots=[AnswerSlot(slot_id="r1", label="answer")],
        reviewed_scope=ReviewedScope(tenant_id=tenant),
    )


def test_reference_packs_implement_all_seven_surfaces_without_cross_imports():
    for contribution in (build_hr(), build_manufacturing()):
        assert all(getattr(contribution, field.name) for field in fields(contribution))
        for component in contribution.all_components:
            module_name, attribute = component.component_path.split(":", 1)
            assert callable(getattr(importlib.import_module(module_name), attribute))

    hr_source = (ROOT / "app/packs/hr_knowledge/contributions.py").read_text(encoding="utf-8")
    manufacturing_source = (ROOT / "app/packs/manufacturing_knowledge/contributions.py").read_text(encoding="utf-8")
    assert "manufacturing_knowledge" not in hr_source
    assert "hr_knowledge" not in manufacturing_source


def test_domain_ontologies_and_corpora_do_not_leak_facets():
    from app.packs.hr_knowledge.contributions import HR_ONTOLOGY
    from app.packs.manufacturing_knowledge.contributions import MANUFACTURING_ONTOLOGY

    assert not {"equipment_model", "procedure_step", "process_parameter", "anomaly"}.intersection(HR_ONTOLOGY)
    assert not {"benefit", "leave_rule", "eligibility"}.intersection(MANUFACTURING_ONTOLOGY)


def test_core_contract_runs_without_any_pack_and_schema_is_domain_neutral():
    decision = decide_evidence(_contract("t1"), [_evidence("t1")])
    assert decision.action == "answer"
    assert decision.pack_versions == {}

    hr = decide_evidence(_contract("t1"), [_evidence("t1")], pack_versions={"hr_knowledge": "1.0.0"})
    mfg = decide_evidence(_contract("t1"), [_evidence("t1")], pack_versions={"manufacturing_knowledge": "1.0.0"})
    assert set(hr.to_dict()) == set(mfg.to_dict()) == {field.name for field in fields(EvidenceDecision)}


def test_disable_and_uninstall_remove_every_contribution_atomically():
    runtime = KnowledgePackRuntime()
    runtime.install("hr_knowledge", "1.0.0", build_hr())
    runtime.enable("t1", "hr_knowledge")
    assert len(runtime.components("t1")) == 7
    assert runtime.versions("t1") == {"hr_knowledge": "1.0.0"}

    runtime.disable("t1", "hr_knowledge")
    assert runtime.components("t1") == ()
    runtime.enable("t1", "hr_knowledge")
    runtime.uninstall("hr_knowledge")
    assert runtime.active("t1") == ()
    assert runtime.versions("t1") == {}


def test_alias_resolution_is_tenant_scoped_and_provider_failure_is_not_absence():
    runtime = KnowledgePackRuntime()
    runtime.install("hr_knowledge", "1.0.0", build_hr())
    runtime.enable("tenant-a", "hr_knowledge")
    assert runtime.resolve_aliases("tenant-b", "pto", lambda _: lambda *_: ("secret-a",)) == ()
    assert "paid_time_off" in runtime.resolve_aliases(
        "tenant-a",
        "pto",
        lambda path: getattr(importlib.import_module(path.split(":")[0]), path.split(":")[1]),
    )

    failed = admit_pack_candidates(
        [_candidate("hr_knowledge", "tenant-a")],
        tenant_id="tenant-a",
        active_pack_key="hr_knowledge",
        authority_verifier=lambda _: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert failed.execution_status is ExecutionStatus.PACK_FAILURE
    decision = decide_evidence(_contract("tenant-a"), [], execution_status=failed.execution_status)
    assert decision.evidence_state != "absent"
    assert decision.action == "error"


def test_core_rechecks_tenant_acl_revision_and_high_risk_formal_authority():
    cross_tenant = admit_pack_candidates(
        [_candidate("hr_knowledge", "tenant-b")],
        tenant_id="tenant-a",
        active_pack_key="hr_knowledge",
        authority_verifier=lambda _: _evidence("tenant-b"),
    )
    assert cross_tenant.execution_status is ExecutionStatus.SCHEMA_ERROR
    assert cross_tenant.evidence == ()

    unsafe = admit_pack_candidates(
        [_candidate("manufacturing_knowledge", "tenant-a", risk="high")],
        tenant_id="tenant-a",
        active_pack_key="manufacturing_knowledge",
        authority_verifier=lambda _: _evidence("tenant-a", "primary_document"),
    )
    assert unsafe.evidence == ()

    safe = admit_pack_candidates(
        [_candidate("manufacturing_knowledge", "tenant-a", risk="high")],
        tenant_id="tenant-a",
        active_pack_key="manufacturing_knowledge",
        authority_verifier=lambda _: _evidence("tenant-a", "formally_approved_sop"),
    )
    assert len(safe.evidence) == 1


def test_packs_have_no_direct_database_or_index_bypass_imports():
    forbidden_imports = {"sqlalchemy", "app.models", "app.db", "app.services.retrieval"}
    for folder in (ROOT / "app/packs/hr_knowledge", ROOT / "app/packs/manufacturing_knowledge"):
        for path in folder.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imports = {
                alias.name
                for node in ast.walk(tree)
                for alias in (
                    node.names if isinstance(node, ast.Import) else [ast.alias(name=node.module or "")]
                    if isinstance(node, ast.ImportFrom)
                    else []
                )
            }
            assert not any(any(name == blocked or name.startswith(blocked + ".") for blocked in forbidden_imports) for name in imports)


def test_generic_core_has_no_hr_or_manufacturing_domain_contamination():
    core_files = (
        ROOT / "app/services/evidence_contract.py",
        ROOT / "app/services/evidence_orchestrator.py",
        ROOT / "app/platform/packs/knowledge.py",
    )
    forbidden = ("paid_time_off", "leave_rule", "equipment_model", "process_parameter")
    assert all(token not in path.read_text(encoding="utf-8") for path in core_files for token in forbidden)
