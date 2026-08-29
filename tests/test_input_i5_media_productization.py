from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.services.media_productization import (
    AudioProbe,
    MediaPolicyError,
    create_browser_audio_proxy,
    create_browser_video_proxy,
    extract_audio_chunks,
    parse_audio_probe_payload,
    validate_audio_probe,
)
from app.services.media_quality import (
    TimelineObservation,
    candidate_publication_allowed,
    evaluate_media_matrix,
    evaluate_timeline_alignment,
)
from app.services.video_processing import VideoProbe, process_video_file
from app.tasks.audio_tasks import _segment_digest


@pytest.mark.parametrize(
    ("codec", "format_name"),
    [
        ("mp3", "mp3"),
        ("pcm_s16le", "wav"),
        ("aac", "mov,mp4,m4a"),
        ("vorbis", "ogg"),
        ("flac", "flac"),
        ("opus", "matroska,webm"),
    ],
)
def test_audio_probe_accepts_product_codec_matrix(codec, format_name):
    probe = parse_audio_probe_payload(
        {
            "streams": [{
                "codec_type": "audio", "codec_name": codec,
                "sample_rate": "16000", "channels": 1,
            }],
            "format": {"duration": "12.5", "format_name": format_name},
        }
    )
    validate_audio_probe(probe)
    assert probe.duration_ms == 12_500


def test_audio_probe_fails_closed_for_unknown_codec(monkeypatch):
    monkeypatch.setattr("app.config.settings.AUDIO_ALLOWED_CODECS", "aac,flac")
    with pytest.raises(MediaPolicyError, match="unsupported audio codec"):
        validate_audio_probe(AudioProbe(1_000, "evil", "bin", 1, 1))


def test_audio_chunking_is_bounded_and_sorted(tmp_path):
    commands = []

    def runner(command, *, timeout):
        commands.append((command, timeout))
        pattern = command[-1]
        Path(pattern.replace("%05d", "00001")).write_bytes(b"b")
        Path(pattern.replace("%05d", "00000")).write_bytes(b"a")
        return subprocess.CompletedProcess(command, 0, "", "")

    chunks = extract_audio_chunks(
        "source.flac", str(tmp_path), chunk_seconds=300, runner=runner
    )
    assert [Path(path).name for path in chunks] == ["audio-00000.mp3", "audio-00001.mp3"]
    assert commands[0][0][commands[0][0].index("-segment_time") + 1] == "300"
    assert commands[0][1] == 3600


def test_video_proxy_is_browser_safe_and_faststart(tmp_path):
    commands = []

    def runner(command, *, timeout):
        commands.append(command)
        Path(command[-1]).write_bytes(b"proxy")
        return subprocess.CompletedProcess(command, 0, "", "")

    target = str(tmp_path / "proxy.mp4")
    assert create_browser_video_proxy("source.mkv", target, runner=runner) == target
    command = commands[0]
    assert command[command.index("-c:v") + 1] == "libx264"
    assert command[command.index("-c:a") + 1] == "aac"
    assert command[command.index("-movflags") + 1] == "+faststart"
    assert "yuv420p" in command


def test_audio_proxy_is_browser_safe_and_bounded(tmp_path):
    commands = []

    def runner(command, *, timeout):
        commands.append((command, timeout))
        Path(command[-1]).write_bytes(b"proxy")
        return subprocess.CompletedProcess(command, 0, "", "")

    target = str(tmp_path / "proxy.mp3")
    assert create_browser_audio_proxy("source.flac", target, runner=runner) == target
    command, timeout = commands[0]
    assert command[command.index("-c:a") + 1] == "libmp3lame"
    assert command[command.index("-b:a") + 1] == "96k"
    assert timeout == 3600


def test_video_pipeline_emits_ordered_partial_readiness(tmp_path):
    events = []

    def runner(command, *, timeout):
        output = command[-1]
        if "silencedetect=noise=-45dB:d=0.1" in command:
            return subprocess.CompletedProcess(command, 0, "", "")
        if "%04d" in output:
            Path(output.replace("%04d", "0000")).write_bytes(b"audio")
        elif output.endswith(".jpg"):
            Path(output).write_bytes(b"frame")
        return subprocess.CompletedProcess(command, 0, "", "")

    process_video_file(
        "source.mp4", str(tmp_path),
        probe=VideoProbe(20_000, 640, 360, "h264", "aac", 25.0, "mp4"),
        runner=runner,
        stt=lambda _path: ([{"start": 1, "end": 3, "text": "確認壓力歸零"}], 0.9),
        ocr=lambda _path: ("0 bar", 0.95),
        progress=lambda phase, detail: events.append((phase, detail)),
    )
    phases = [phase for phase, _detail in events]
    assert phases[:3] == ["probe_complete", "audio_demuxed", "transcript_partial"]
    assert "keyframes_extracted" in phases
    assert phases[-1] == "visual_partial"


def test_repeated_text_at_different_times_does_not_collapse():
    first = _segment_digest(text="檢查", start_ms=0, end_ms=1000, speaker="A")
    second = _segment_digest(text="檢查", start_ms=300_000, end_ms=301_000, speaker="A")
    assert first != second


def test_timeline_error_and_codec_matrix_are_fail_closed():
    report = evaluate_timeline_alignment([
        TimelineObservation(1_000, 1_200, 2_000, 2_250),
        TimelineObservation(5_000, 5_300),
    ])
    assert report["status"] == "PASS"
    assert report["max_absolute_error_ms"] == 300
    assert evaluate_timeline_alignment([])["status"] == "FAIL"

    matrix = evaluate_media_matrix(
        [{"extension": ".mp4", "status": "PASS"}],
        required_extensions={".mp4", ".mkv"},
    )
    assert matrix["status"] == "FAIL"
    assert matrix["missing_extensions"] == [".mkv"]


def test_candidate_cannot_publish_without_review_or_with_conflict():
    assert not candidate_publication_allowed(
        confidence=0.99, has_unresolved_conflict=False, reviewed=False
    )
    assert not candidate_publication_allowed(
        confidence=0.99, has_unresolved_conflict=True, reviewed=True
    )
    assert candidate_publication_allowed(
        confidence=0.9, has_unresolved_conflict=False, reviewed=True
    )


def test_i5_migration_contains_proxy_and_reversible_constraint():
    migration = Path(
        "app/db/migrations/versions/input_i5_media_productization_001.py"
    ).read_text(encoding="utf-8")
    assert 'revision: str = "input_i5_media_product_001"' in migration
    assert "input_i4_evidence_precision_001" in migration
    assert "'media_proxy'" in migration
    assert "def downgrade" in migration
