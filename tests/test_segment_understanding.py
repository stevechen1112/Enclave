from __future__ import annotations

import pytest

from app.platform.multimodal import (
    MultimodalSegmentCandidate,
    MultimodalSegmentInput,
    SegmentEvidence,
)
from app.services.segment_understanding import (
    ConservativeSegmentProvider,
    EvidenceCompletenessError,
    build_segments,
    understand_segments,
    validate_candidates,
)


def _segment():
    return MultimodalSegmentInput(
        "s1",
        0,
        10_000,
        (
            SegmentEvidence("asr", "transcript_segment", 0, 5000, "壓力 2.5 MPa"),
            SegmentEvidence("ocr", "ocr_region", 2000, 2001, "壓力 3.0 MPa"),
            SegmentEvidence("action", "action_event", 3000, 5000, "確認壓力"),
        ),
    )


def test_foreign_evidence_reference_is_rejected():
    with pytest.raises(EvidenceCompletenessError, match="foreign evidence"):
        validate_candidates(
            _segment(), [MultimodalSegmentCandidate("action", "動作", ("other",))]
        )


def test_conservative_provider_detects_numeric_contradiction_and_keeps_review_gate():
    rows = ConservativeSegmentProvider().understand(_segment())
    contradiction = next(row for row in rows if row.candidate_type == "contradiction")
    assert contradiction.risk_level == "high"
    assert contradiction.attributes["requires_human_review"] is True


def test_provider_failure_degrades_without_unsupported_output():
    class Broken:
        provider_key = "broken"
        provider_version = "1"
        execution_boundary = "test"

        def understand(self, segment):
            raise TimeoutError("provider unavailable")

    result = understand_segments([_segment()], Broken())[0]
    assert result.provider_state == "degraded_provider_failure"
    assert result.candidates == ()


def test_segments_cover_duration_and_do_not_cross_bind_evidence():
    evidence = [SegmentEvidence("a", "transcript_segment", 31_000, 32_000, "第二段")]
    segments = build_segments(evidence, duration_ms=60_000)
    assert len(segments) == 2
    assert not segments[0].evidence
    assert segments[1].evidence[0].artifact_id == "a"
