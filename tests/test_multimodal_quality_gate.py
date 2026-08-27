from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from app.eval.multimodal_quality import (
    CorpusValidationError,
    Thresholds,
    aggregate_matrix,
    build_contract_results,
    evaluate,
    load_json,
    validate_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "testdata" / "multimodal_golden" / "manifest.json"


@pytest.fixture
def manifest():
    return load_json(MANIFEST_PATH)


def test_manifest_covers_required_modalities_and_slices(manifest):
    cases = validate_manifest(manifest)
    assert {case["modality"] for case in cases} == {"document", "spreadsheet", "image", "audio", "video"}
    slices = {case["slice"] for case in cases}
    assert {"pdf_native", "pdf_scanned", "docx_native", "xlsx_formula_table", "csv_structured"} <= slices
    assert {"quiet_single_speaker", "noisy_low_confidence", "multi_speaker", "long_recording"} <= slices
    assert {"fixed_with_subtitles", "fixed_no_subtitles", "handheld_motion", "equipment_high_risk_sop_conflict"} <= slices


def test_contract_gate_passes_and_is_not_live_evidence(manifest):
    bundle = build_contract_results(manifest, "mock_contract", "fixture", "1")
    report = evaluate(manifest, bundle)
    assert report["status"] == "PASS"
    assert report["evidence_class"] == "contract_only"
    assert report["case_count"] == 15
    assert report["per_slice"]


def test_degraded_provider_abstains_and_passes_only_safety_contract(manifest):
    bundle = build_contract_results(manifest, "degraded", "disabled-provider", "1")
    report = evaluate(manifest, bundle)
    assert report["status"] == "PASS"
    assert report["evidence_locator_applicable"] is False
    assert report["critical_error_count"] == 0


@pytest.mark.parametrize(
    ("mutation", "critical_key"),
    [
        (lambda row: row.update(tenant_id="tenant-b"), "cross_tenant_leaks"),
        (lambda row: row["answer"].update(status="answered", grounded=False), "hallucinations"),
    ],
)
def test_critical_failures_are_fail_closed(manifest, mutation, critical_key):
    bundle = build_contract_results(manifest, "mock_contract", "fixture", "1")
    mutation(bundle["results"][0])
    report = evaluate(manifest, bundle)
    assert report["status"] == "FAIL"
    assert report["critical_errors"][critical_key] == 1


def test_wrong_revision_citation_fails(manifest):
    bundle = build_contract_results(manifest, "mock_contract", "fixture", "1")
    bundle["results"][0]["answer"] = {
        "status": "answered", "grounded": True, "authoritative": True,
        "citations": [{"revision_id": "old-revision"}],
    }
    report = evaluate(manifest, bundle)
    assert report["status"] == "FAIL"
    assert report["critical_errors"]["wrong_revision_citations"] == 1


def test_high_risk_answer_without_authority_fails(manifest):
    bundle = build_contract_results(manifest, "mock_contract", "fixture", "1")
    row = next(item for item in bundle["results"] if item["case_id"] == "video-machine-001")
    row["answer"] = {"status": "answered", "grounded": True, "authoritative": False, "citations": []}
    report = evaluate(manifest, bundle)
    assert report["critical_errors"]["unsafe_high_risk_answers"] == 1
    assert report["status"] == "FAIL"


def test_low_confidence_and_sop_conflict_fail_closed(manifest):
    bundle = build_contract_results(manifest, "mock_contract", "fixture", "1")
    row = next(item for item in bundle["results"] if item["case_id"] == "video-machine-001")
    row["review_created"] = False
    row["sop_conflict_detected"] = False
    report = evaluate(manifest, bundle)
    assert report["critical_errors"]["low_confidence_unreviewed"] == 1
    assert report["critical_errors"]["sop_conflict_misses"] == 1


def test_locator_precision_and_recall_cannot_be_hidden_by_average(manifest):
    bundle = build_contract_results(manifest, "mock_contract", "fixture", "1")
    row = bundle["results"][0]
    row["evidence_locators"] = [{"id": "wrong", "kind": "page", "page": 99, "revision_id": "rev-doc-001"}]
    report = evaluate(
        manifest,
        bundle,
        Thresholds(evidence_locator_precision_min=0.5, evidence_locator_recall_min=0.5),
    )
    assert report["status"] == "FAIL"
    assert report["checks"]["evidence_locator_precision"] is True
    assert report["checks"]["per_slice_evidence_locator"] is False
    assert report["per_slice"]["document:pdf_native"]["locator_precision"] == 0.0


def test_result_bundle_must_match_corpus_hash(manifest):
    bundle = build_contract_results(manifest, "mock_contract", "fixture", "1")
    bundle["corpus_sha256"] = "0" * 64
    with pytest.raises(CorpusValidationError, match="does not match"):
        evaluate(manifest, bundle)


def test_matrix_requires_distinct_modes(manifest):
    contract = evaluate(manifest, build_contract_results(manifest, "mock_contract", "fixture", "1"))
    matrix = aggregate_matrix([contract], ["mock_contract", "degraded"])
    assert matrix["status"] == "FAIL"
    assert matrix["missing_modes"] == ["degraded"]


def test_matrix_rejects_duplicate_mode_reports(manifest):
    contract = evaluate(manifest, build_contract_results(manifest, "mock_contract", "fixture", "1"))
    matrix = aggregate_matrix([contract, contract], ["mock_contract"])
    assert matrix["status"] == "FAIL"
    assert matrix["duplicate_modes"] == ["mock_contract"]


def test_cross_tenant_evidence_locator_is_critical(manifest):
    bundle = build_contract_results(manifest, "mock_contract", "fixture", "1")
    bundle["results"][0]["evidence_locators"][0]["tenant_id"] = "tenant-b"
    report = evaluate(manifest, bundle)
    assert report["status"] == "FAIL"
    assert report["critical_errors"]["cross_tenant_leaks"] == 1


def test_internal_replay_cannot_be_synthesized_by_cli():
    completed = subprocess.run(
        [sys.executable, "scripts/run_multimodal_quality_gate.py", "--mode", "internal_replay"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert "--results is mandatory" in completed.stderr


def test_internal_replay_requires_immutable_provenance(manifest):
    bundle = build_contract_results(manifest, "mock_contract", "fixture", "1")
    bundle["mode"] = "internal_replay"
    with pytest.raises(CorpusValidationError, match="run_id"):
        evaluate(manifest, bundle)
