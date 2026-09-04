from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from scripts.audit_asset_parse_quality import _confidence, _normalise_text, _span_metrics


def test_confidence_keeps_unknown_distinct_from_measured_zero() -> None:
    result = _confidence([None, 0.0, 0.52, 0.91])

    assert result == {
        "known_count": 2,
        "unknown_count": 1,
        "zero_sentinel_count": 1,
        "below_0_8_count": 1,
        "min": 0.52,
        "mean": 0.715,
        "max": 0.91,
    }


def test_timeline_reach_and_evidence_coverage_are_source_neutral() -> None:
    first_id, second_id = uuid4(), uuid4()
    artifacts = [SimpleNamespace(id=first_id), SimpleNamespace(id=second_id)]
    spans = {
        first_id: [SimpleNamespace(start_ms=500, end_ms=4_000, speaker="speaker_0")],
        second_id: [SimpleNamespace(start_ms=7_000, end_ms=9_500, speaker=None)],
    }

    result = _span_metrics(artifacts, spans, duration_ms=10_000)

    assert result["artifact_count"] == 2
    assert result["artifacts_with_evidence"] == 2
    assert result["first_start_ms"] == 500
    assert result["last_end_ms"] == 9_500
    assert result["timeline_reach_ratio"] == 0.95
    assert result["speaker_labeled_count"] == 1


def test_text_normalisation_supports_cross_format_consistency_checks() -> None:
    assert _normalise_text("勞保，不能不保！") == _normalise_text("勞保 不能不保")
