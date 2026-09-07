from __future__ import annotations

import pytest

from app.services import input_capability_results as subject


def test_complete_capability_results_fails_closed_for_missing_result():
    completed = subject.complete_capability_results(
        ["extract_text", "layout"],
        {"extract_text": subject.capability_result("available", artifact_count=2)},
    )

    assert completed["extract_text"]["status"] == "available"
    assert completed["layout"]["status"] == "failed"
    assert completed["layout"]["reason_code"] == "capability_result_missing"


def test_complete_capability_results_rejects_registry_drift():
    with pytest.raises(ValueError, match="unrequested capability"):
        subject.complete_capability_results(
            ["extract_text"],
            {
                "extract_text": subject.capability_result("available"),
                "ocr": subject.capability_result("available"),
            },
        )


@pytest.mark.parametrize(
    "malformed",
    [
        {"status": "unknown", "artifact_count": 0},
        {"status": "available", "artifact_count": -1},
        {"status": "available", "artifact_count": 0, "provider": "openai"},
        {
            "status": "available",
            "artifact_count": 0,
            "provider": {"confidence_provider_supplied": "false"},
        },
        {"status": "available", "artifact_count": 0, "details": []},
    ],
)
def test_complete_capability_results_rejects_malformed_payload(malformed):
    with pytest.raises(ValueError):
        subject.complete_capability_results(["transcribe"], {"transcribe": malformed})


def test_non_available_result_requires_machine_readable_reason():
    with pytest.raises(ValueError, match="requires a reason_code"):
        subject.capability_result("degraded")


def test_transcription_default_confidence_is_unknown_not_zero():
    from app.services.voice_gateway import TranscriptionResult

    result = TranscriptionResult(text="測試")

    assert result.confidence is None
    assert result.confidence_provider_supplied is False


def test_audio_no_speech_is_not_a_processing_failure():
    results = subject.audio_capability_results(
        ["transcribe", "timestamp", "terminology_correction"],
        transcript_count=0,
        audio_chunk_count=2,
        preview_ready=True,
        provider="openai",
        model="gpt-4o-transcribe-diarize",
    )

    assert results["transcribe"]["status"] == "not_applicable"
    assert results["transcribe"]["reason_code"] == "no_speech_detected"
    assert results["transcribe"]["provider"]["confidence_provider_supplied"] is False
    assert results["timestamp"]["status"] == "not_applicable"
    assert results["terminology_correction"]["status"] == "degraded"


def test_video_reports_each_requested_capability_without_claiming_empty_ocr():
    requested = [
        "probe_metadata",
        "demux_audio",
        "transcribe",
        "keyframe",
        "ocr",
        "scene_segment",
        "audio_event",
        "procedure_candidate",
    ]
    results = subject.video_capability_results(
        requested,
        has_audio=True,
        audio_chunk_count=1,
        transcript_count=4,
        keyframe_count=3,
        ocr_count=0,
        procedure_artifact_id="procedure-1",
        preview_ready=True,
        capability_states={
            "scene_segmentation": "available",
            "audio_anomaly": "insufficient_signal",
        },
        stt_model="gpt-4o-transcribe-diarize",
    )

    assert set(results) == set(requested)
    assert results["ocr"]["status"] == "not_applicable"
    assert results["ocr"]["reason_code"] == "no_text_detected"
    assert results["ocr"]["provider"]["confidence_provider_supplied"] is False
    assert results["ocr"]["provider"]["calibration_version"] == "unavailable"
    assert results["audio_event"]["status"] == "degraded"
    assert results["transcribe"]["provider"]["model"] == "gpt-4o-transcribe-diarize"


def test_readiness_contains_reproducible_non_secret_runtime_identity(monkeypatch):
    subject._cached_input_runtime_identity.cache_clear()
    monkeypatch.setattr(
        subject,
        "_dependency_version",
        lambda command, *arguments: {
            "available": command == "ffmpeg",
            "version": "v1" if command == "ffmpeg" else None,
        },
    )
    monkeypatch.setattr(subject, "package_version", lambda name: "1.2.3")

    readiness = subject.readiness_with_capability_results(
        {"searchable": False},
        requested_capabilities=["transcribe"],
        observed={"transcribe": subject.capability_result("available")},
    )

    identity = readiness["runtime_identity"]
    assert readiness["capability_results_schema"] == "input-capability-results.v1"
    assert len(identity["identity_hash"]) == 64
    assert identity["native_dependencies"]["ffmpeg"]["available"] is True
    assert identity["native_dependencies"]["tesseract"]["available"] is False
    assert "environment" not in identity
    subject._cached_input_runtime_identity.cache_clear()


def test_runtime_identity_callers_cannot_mutate_cached_evidence(monkeypatch):
    subject._cached_input_runtime_identity.cache_clear()
    monkeypatch.setattr(
        subject,
        "_dependency_version",
        lambda command, *arguments: {"available": True, "version": command},
    )

    first = subject.input_runtime_identity()
    first["native_dependencies"]["ffmpeg"]["version"] = "tampered"
    second = subject.input_runtime_identity()

    assert second["native_dependencies"]["ffmpeg"]["version"] == "ffmpeg"
    subject._cached_input_runtime_identity.cache_clear()


def test_dependency_probe_failure_is_recorded_without_raising(monkeypatch):
    monkeypatch.setattr(subject.shutil, "which", lambda _command: "C:/bin/tool.exe")
    monkeypatch.setattr(
        subject.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            UnicodeDecodeError("utf-8", b"x", 0, 1, "bad")
        ),
    )

    assert subject._dependency_version("ffmpeg", "-version") == {
        "available": False,
        "version": None,
    }


def test_video_without_audio_reports_diarization_as_not_applicable():
    result = subject.video_capability_results(
        ["diarize"],
        has_audio=False,
        audio_chunk_count=0,
        transcript_count=0,
        keyframe_count=1,
        ocr_count=0,
        procedure_artifact_id=None,
        preview_ready=False,
        capability_states={},
    )["diarize"]

    assert result["status"] == "not_applicable"
    assert result["reason_code"] == "no_audio_track"


def test_video_provider_failure_is_scoped_to_the_affected_capability():
    results = subject.video_capability_results(
        ["scene_segment", "audio_event"],
        has_audio=True,
        audio_chunk_count=1,
        transcript_count=0,
        keyframe_count=1,
        ocr_count=0,
        procedure_artifact_id=None,
        preview_ready=False,
        capability_states={
            "scene_segmentation": "failed",
            "audio_anomaly": "failed",
        },
        provider_failures=[
            {"provider": "scene.provider", "capabilities": ["scene_segmentation"]},
            {"provider": "audio.provider", "capabilities": ["audio_anomaly"]},
        ],
    )

    assert results["scene_segment"]["details"]["failed_providers"] == ["scene.provider"]
    assert results["audio_event"]["details"]["failed_providers"] == ["audio.provider"]


def test_document_capabilities_preserve_exact_requested_contract():
    results = subject.document_capability_results(
        ["extract_text", "ocr"],
        content_chars=120,
        chunk_count=2,
        parse_engine="native/image",
        parser_version="1",
        ocr_used=True,
    )

    assert set(results) == {"extract_text", "ocr"}
    assert results["extract_text"]["status"] == "available"
    assert results["ocr"]["status"] == "available"


def test_document_capabilities_do_not_claim_placeholder_as_extracted_text():
    results = subject.document_capability_results(
        ["extract_text", "ocr"],
        content_chars=50,
        chunk_count=1,
        parse_engine="native/image",
        parser_version="1",
        ocr_used=True,
        machine_readable_content=False,
    )

    assert results["extract_text"]["status"] == "degraded"
    assert results["extract_text"]["reason_code"] == "manual_description_required"
    assert results["extract_text"]["artifact_count"] == 0
    assert results["ocr"]["status"] == "not_applicable"
    assert results["ocr"]["artifact_count"] == 0


def test_document_layout_is_not_overclaimed_without_fidelity_measurement():
    results = subject.document_capability_results(
        ["extract_text", "layout"],
        content_chars=120,
        chunk_count=2,
        parse_engine="native/pdf",
        parser_version="1",
        ocr_used=False,
    )

    assert results["extract_text"]["status"] == "available"
    assert results["layout"]["status"] == "degraded"
    assert results["layout"]["reason_code"] == "layout_fidelity_not_measured"
