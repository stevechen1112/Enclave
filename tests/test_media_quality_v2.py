from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from app.eval.media_quality_v2 import (
    MediaTruthError,
    corpus_sha256,
    error_rate,
    evaluate_media_quality,
    validate_truth_manifest,
)


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def manifest():
    return json.loads(
        (ROOT / "testdata/media_quality_v2/manifest.template.json").read_text(
            encoding="utf-8"
        )
    )


def _results(manifest):
    return {
        "corpus_sha256": corpus_sha256(manifest),
        "provenance": {
            "run_id": "run-1",
            "captured_at": "2026-09-05T01:00:00+08:00",
            "source_commit": "a" * 40,
            "runtime_manifest_hash": "b" * 64,
        },
        "results": [
            {
                "case_id": case["id"],
                "tenant_id": case["tenant_id"],
                "predicted": deepcopy(case["truth"]),
                "answer_status": "answered",
                "evidence_complete": True,
            }
            for case in manifest["cases"]
        ],
    }


def test_character_error_rate_handles_chinese_without_word_boundaries():
    assert error_rate("壓力歸零", "壓力歸零", unit="character") == 0
    assert error_rate("壓力歸零", "壓力歸一", unit="character") == 0.25


def test_perfect_replay_passes_but_keeps_regression_evidence_class(manifest):
    report = evaluate_media_quality(manifest, _results(manifest))
    assert report["status"] == "PASS"
    assert report["evidence_class"] == "development_regression"
    assert report["critical_event_recall"] == 1


def test_result_must_bind_to_immutable_corpus(manifest):
    results = _results(manifest)
    results["corpus_sha256"] = "0" * 64
    with pytest.raises(MediaTruthError, match="not bound"):
        evaluate_media_quality(manifest, results)


def test_tenant_acceptance_requires_truth_owner(manifest):
    manifest["classification"] = "tenant_acceptance"
    with pytest.raises(MediaTruthError, match="truth_owner"):
        validate_truth_manifest(manifest)


def test_critical_omission_and_unsupported_answer_fail_gate(manifest):
    results = _results(manifest)
    row = results["results"][0]
    row["predicted"]["transcript"] = "設備的設定。"
    row["evidence_complete"] = False
    report = evaluate_media_quality(manifest, results)
    assert report["status"] == "FAIL"
    assert report["checks"]["critical_term_recall"] is False
    assert report["unsupported_high_risk"] == 1


def test_cross_tenant_result_is_never_averaged_away(manifest):
    results = _results(manifest)
    results["results"][0]["tenant_id"] = "other-tenant"
    report = evaluate_media_quality(manifest, results)
    assert report["status"] == "FAIL"
    assert report["cross_tenant_leaks"] == 1


def test_median_gate_and_repetition_are_reported_per_case(manifest):
    results = _results(manifest)
    first = results["results"][0]
    first["predicted"]["transcript"] = "重複 重複 重複"
    report = evaluate_media_quality(manifest, results)
    slice_metrics = report["per_slice"][manifest["cases"][0]["slice"]]
    assert "median_cer" in slice_metrics
    assert report["repetition_candidates"][manifest["cases"][0]["id"]] == ["重複"]


def test_forbidden_high_risk_insertion_fails_gate(manifest):
    manifest["cases"][0]["truth"]["forbidden_terms"] = ["解除安全門"]
    results = _results(manifest)
    results["corpus_sha256"] = corpus_sha256(manifest)
    results["results"][0]["predicted"]["summary"] = "解除安全門"
    report = evaluate_media_quality(manifest, results)
    assert report["checks"]["forbidden_term_insertion"] is False
