from __future__ import annotations

import pytest

from app.services.input_quality import (
    GeneralizationQualityThresholds,
    assess_evidence_claim,
    character_error_rate,
    evaluate_generalization_quality,
    normalize_provider_confidence,
    word_error_rate,
)


def _text_case(
    case_id: str,
    *,
    slice_name: str = "factory_speech",
    evidence_class: str = "tenant_real",
    reference: str = "確認壓力歸零後停機",
    hypothesis: str = "確認壓力歸零後停機",
) -> dict:
    return {
        "id": case_id,
        "slice": slice_name,
        "evidence_class": evidence_class,
        "ground_truth_verified": True,
        "parse_success": True,
        "reference": reference,
        "hypothesis": hypothesis,
        "locator_complete": True,
    }


def test_full_text_error_metrics_do_not_treat_substring_as_perfect() -> None:
    reference = "確認壓力歸零"
    hypothesis = "前言與無關內容確認壓力歸零後續幻覺內容"

    assert character_error_rate(reference, hypothesis) > 0
    assert word_error_rate(reference, hypothesis) > 0


def test_synthetic_pass_cannot_certify_semantic_quality() -> None:
    rows = [
        _text_case(str(index), evidence_class="synthetic") for index in range(5)
    ]

    result = evaluate_generalization_quality(
        rows,
        required_slices=["factory_speech"],
        requested_claim="semantic",
    )

    assert result["status"] == "HOLD"
    assert result["claim_ceiling"] == "mechanical"
    assert "cannot support" in " ".join(
        result["slices"]["factory_speech"]["blocking_reasons"]
    )


def test_execution_pass_remains_hold_when_claim_exceeds_evidence() -> None:
    result = assess_evidence_claim(
        evidence_class="SEALED_INTERNAL_SYNTHETIC",
        execution_status="PASS",
        requested_claim="semantic",
        declared_gaps=["real factory speech is missing"],
    )

    assert result["status"] == "HOLD"
    assert result["claim_ceiling"] == "mechanical"
    assert result["execution_status"] == "PASS"


def test_truth_backed_real_slice_can_pass_semantic_gate() -> None:
    rows = [_text_case(str(index)) for index in range(5)]

    result = evaluate_generalization_quality(
        rows,
        required_slices=["factory_speech"],
        requested_claim="semantic",
    )

    speech = result["slices"]["factory_speech"]
    assert result["status"] == "PASS"
    assert result["claim_ceiling"] == "semantic"
    assert speech["semantic_pass_count"] == 5
    assert speech["semantic_pass_rate_wilson_95"][0] < 1.0


def test_missing_required_slice_holds_the_whole_claim() -> None:
    rows = [_text_case(str(index)) for index in range(5)]

    result = evaluate_generalization_quality(
        rows,
        required_slices=["factory_speech", "machine_noise"],
    )

    assert result["status"] == "HOLD"
    assert result["slices"]["machine_noise"]["sample_count"] == 0


def test_one_bad_case_fails_even_when_aggregate_cer_would_pass() -> None:
    rows = [_text_case(str(index)) for index in range(9)]
    rows.append(_text_case("bad", hypothesis="完全錯誤的內容"))

    result = evaluate_generalization_quality(
        rows,
        required_slices=["factory_speech"],
        thresholds=GeneralizationQualityThresholds(max_cer=0.15),
    )

    assert result["status"] == "FAIL"
    assert "bad" in result["slices"]["factory_speech"]["measured_failures"]


def test_critical_field_mismatch_fails_closed() -> None:
    rows = [_text_case(str(index)) for index in range(5)]
    rows[2]["critical_fields"] = [
        {"name": "壓力", "expected": "6.5 BAR", "actual": "65 BAR"}
    ]

    result = evaluate_generalization_quality(
        rows,
        required_slices=["factory_speech"],
    )

    assert result["status"] == "FAIL"
    assert result["slices"]["factory_speech"]["critical_field_exact"] == {
        "successes": 0,
        "total": 1,
        "rate": 0.0,
    }


def test_verified_no_speech_is_not_a_processing_failure() -> None:
    rows = [
        {
            "id": str(index),
            "slice": "silent_video",
            "evidence_class": "tenant_real",
            "ground_truth_verified": True,
            "parse_success": False,
            "capability_outcome": "no_speech",
            "expected_outcome": "no_speech",
            "locator_complete": False,
        }
        for index in range(5)
    ]

    result = evaluate_generalization_quality(
        rows,
        required_slices=["silent_video"],
    )

    assert result["status"] == "PASS"
    assert result["slices"]["silent_video"]["semantic_pass_count"] == 5


def test_unknown_confidence_is_distinct_from_measured_zero() -> None:
    assert normalize_provider_confidence(0.0, provider_supplied=False) is None
    assert normalize_provider_confidence(0.0, provider_supplied=True) == 0.0
    with pytest.raises(ValueError):
        normalize_provider_confidence(1.1, provider_supplied=True)
