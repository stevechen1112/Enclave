from collections import Counter

from scripts.backfill_input_capability_results import infer_results


def test_audio_backfill_is_frontend_contract_complete():
    results = infer_results(
        "audio",
        ["background_progress", "transcribe", "timestamp", "terminology_correction"],
        Counter({"transcript_segment": 20, "media_proxy": 1}),
    )
    assert results["transcribe"]["status"] == "available"
    assert results["transcribe"]["artifact_count"] == 20
    assert results["transcribe"]["reason_code"] is None
    assert results["transcribe"]["provider"] is None
    assert results["terminology_correction"]["status"] == "degraded"


def test_video_backfill_does_not_claim_missing_evidence():
    results = infer_results(
        "video",
        ["keyframe", "ocr", "equipment_state", "procedure_candidate"],
        Counter({"keyframe": 6, "ocr_region": 5, "procedure_candidate": 1}),
    )
    assert results["keyframe"]["status"] == "available"
    assert results["ocr"]["artifact_count"] == 5
    assert results["equipment_state"] == {
        "status": "not_applicable",
        "reason_code": "no_evidence_detected",
        "artifact_count": 0,
        "provider": None,
        "details": {"source": "historical_artifact_backfill"},
    }
