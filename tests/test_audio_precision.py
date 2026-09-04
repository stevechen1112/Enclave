from __future__ import annotations

from app.services.audio_precision import (
    AudioQualityProfile,
    TranscriptCandidate,
    build_adaptive_chunk_plan,
    correct_with_approved_glossary,
    extract_critical_tokens,
    merge_overlapping_candidates,
    needs_precision_pass,
    parse_audio_analysis,
    precision_candidate_from_passes,
)


def test_quality_profile_routes_low_volume_and_silence_to_review():
    profile = parse_audio_analysis(
        "mean_volume: -38.0 dB\nmax_volume: -4.0 dB\nsilence_duration: 7.5",
        duration_ms=10_000,
        sample_rate=8_000,
        channels=2,
    )
    assert profile.low_volume is True
    assert {"low_volume", "mostly_silence", "low_sample_rate"} <= set(profile.risks)


def test_adaptive_chunk_plan_is_bounded_and_overlapped():
    plans = build_adaptive_chunk_plan(
        220_000, speech_intervals=[(0, 72_000), (74_000, 148_000), (151_000, 220_000)]
    )
    assert plans[0].start_ms == 0
    assert plans[-1].end_ms == 220_000
    assert all(plan.duration_ms <= 93_000 for plan in plans)
    assert plans[1].overlap_before_ms == 1_500


def test_overlap_merge_prefers_more_complete_text_without_duplicate():
    result = merge_overlapping_candidates(
        [
            TranscriptCandidate(0, 5000, "確認壓力歸零", source_pass="A"),
            TranscriptCandidate(4000, 9000, "請確認壓力歸零", source_pass="B"),
        ]
    )
    assert len(result) == 1
    assert result[0].text == "請確認壓力歸零"
    assert result[0].end_ms == 9000


def test_correction_preserves_explicit_audit_lineage():
    corrected, changes = correct_with_approved_glossary(
        "開啟伺服所", {"伺服所": "事務所"}
    )
    assert corrected == "開啟事務所"
    assert changes == (
        {"from": "伺服所", "to": "事務所", "method": "approved_glossary"},
    )


def test_critical_identifiers_and_measurements_trigger_precision_pass():
    tokens = extract_critical_tokens("設備 A-120 壓力 2.5 MPa", ["設備 A-120"])
    candidate = TranscriptCandidate(
        0, 1000, "設備 A-120 壓力 2.5 MPa", confidence=0.95, critical_tokens=tokens
    )
    profile = AudioQualityProfile(1000, 16000, 1, -20, -2, 0, False, False)
    assert "2.5 MPa" in tokens
    assert needs_precision_pass(candidate, profile) is True


def test_pass_b_difference_remains_reviewable_candidate_not_silent_rewrite():
    plan = build_adaptive_chunk_plan(20_000)[0]
    candidate = precision_candidate_from_passes(
        plan=plan, pass_a_text="開啟伺服所", pass_b_text="開啟事務所", speaker="A"
    )
    assert candidate.source_pass == "B_candidate"
    assert candidate.corrections[0]["method"] == "contextual_asr_candidate"
