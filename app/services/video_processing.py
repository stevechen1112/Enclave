"""Governed video probe, extraction and artifact projection.

External media tools never write database state. Their typed outputs are
projected through the same AssetRevision/DerivedArtifact/EvidenceSpan lineage
used by documents and long-form audio.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models.asset import AssetRevision, DerivedArtifact, EvidenceSpan


class VideoPolicyError(ValueError):
    pass


@dataclass(frozen=True)
class VideoProbe:
    duration_ms: int
    width: int
    height: int
    video_codec: str
    audio_codec: str | None
    frame_rate: float
    format_name: str

    @property
    def has_audio(self) -> bool:
        return self.audio_codec is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "duration_ms": self.duration_ms,
            "width": self.width,
            "height": self.height,
            "video_codec": self.video_codec,
            "audio_codec": self.audio_codec,
            "frame_rate": self.frame_rate,
            "format_name": self.format_name,
            "has_audio": self.has_audio,
        }


@dataclass(frozen=True)
class VideoTranscriptSegment:
    start_ms: int
    end_ms: int
    text: str
    speaker: str | None = None
    confidence: float | None = None


@dataclass
class VideoKeyframe:
    timestamp_ms: int
    frame_index: int
    path: str
    ocr_text: str = ""
    ocr_confidence: float | None = None
    artifact_uri: str | None = None
    storage_key: str | None = None


@dataclass
class VideoProcessingResult:
    probe: VideoProbe
    transcript_segments: list[VideoTranscriptSegment] = field(default_factory=list)
    keyframes: list[VideoKeyframe] = field(default_factory=list)
    audio_chunk_count: int = 0


def _run(command: list[str], *, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _rate(value: str | None) -> float:
    raw = str(value or "0")
    if "/" in raw:
        numerator, denominator = raw.split("/", 1)
        if float(denominator or 0) == 0:
            return 0.0
        return float(numerator) / float(denominator)
    return float(raw or 0)


def parse_probe_payload(payload: dict[str, Any]) -> VideoProbe:
    streams = list(payload.get("streams") or [])
    video = next(
        (stream for stream in streams if stream.get("codec_type") == "video"), None
    )
    if video is None:
        raise VideoPolicyError("video stream not found")
    audio = next(
        (stream for stream in streams if stream.get("codec_type") == "audio"), None
    )
    format_data = dict(payload.get("format") or {})
    duration = format_data.get("duration") or video.get("duration") or 0
    try:
        duration_ms = round(float(duration) * 1000)
    except (TypeError, ValueError) as exc:
        raise VideoPolicyError("video duration is invalid") from exc
    probe = VideoProbe(
        duration_ms=duration_ms,
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
        video_codec=str(video.get("codec_name") or "").lower(),
        audio_codec=(
            str(audio.get("codec_name") or "").lower() if audio is not None else None
        ),
        frame_rate=_rate(video.get("avg_frame_rate") or video.get("r_frame_rate")),
        format_name=str(format_data.get("format_name") or ""),
    )
    if probe.duration_ms <= 0 or probe.width <= 0 or probe.height <= 0:
        raise VideoPolicyError("video metadata is incomplete")
    return probe


def validate_video_probe(probe: VideoProbe) -> None:
    from app.config import settings

    allowed_codecs = {
        item.strip().lower()
        for item in str(settings.VIDEO_ALLOWED_CODECS or "").split(",")
        if item.strip()
    }
    if probe.video_codec not in allowed_codecs:
        raise VideoPolicyError(f"unsupported video codec: {probe.video_codec}")
    if probe.duration_ms > int(settings.VIDEO_MAX_SECONDS) * 1000:
        raise VideoPolicyError("video duration exceeds tenant-safe limit")
    if probe.width > int(settings.VIDEO_MAX_WIDTH) or probe.height > int(
        settings.VIDEO_MAX_HEIGHT
    ):
        raise VideoPolicyError("video resolution exceeds processing limit")


def probe_video(
    path: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = _run,
) -> VideoProbe:
    result = runner(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            path,
        ],
        timeout=60,
    )
    try:
        payload = json.loads(result.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise VideoPolicyError("ffprobe returned invalid metadata") from exc
    probe = parse_probe_payload(payload)
    validate_video_probe(probe)
    return probe


def extract_audio_chunks(
    video_path: str,
    output_dir: str,
    *,
    chunk_seconds: int,
    runner: Callable[..., subprocess.CompletedProcess[str]] = _run,
) -> list[str]:
    pattern = str(Path(output_dir) / "audio-%04d.mp3")
    runner(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            video_path,
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-b:a",
            "48k",
            "-f",
            "segment",
            "-segment_time",
            str(chunk_seconds),
            "-reset_timestamps",
            "1",
            pattern,
        ],
        timeout=1800,
    )
    return [str(path) for path in sorted(Path(output_dir).glob("audio-*.mp3"))]


def extract_keyframes(
    video_path: str,
    output_dir: str,
    probe: VideoProbe,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = _run,
) -> list[VideoKeyframe]:
    from app.config import settings

    duration_seconds = probe.duration_ms / 1000
    interval = max(
        float(settings.VIDEO_KEYFRAME_MIN_INTERVAL_SECONDS),
        duration_seconds / max(1, int(settings.VIDEO_MAX_KEYFRAMES)),
    )
    count = min(
        int(settings.VIDEO_MAX_KEYFRAMES),
        max(1, math.ceil(duration_seconds / interval)),
    )
    keyframes: list[VideoKeyframe] = []
    for index in range(count):
        # Seeking to a container's reported duration can land after its last
        # decodable frame (common with audio-shortened MP4 fixtures and VFR
        # phone video). Keep at least two frame periods inside the stream.
        frame_margin = max(0.250, 2.0 / max(probe.frame_rate, 1.0))
        timestamp_seconds = min(
            index * interval,
            max(0.0, duration_seconds - frame_margin),
        )
        output_path = str(Path(output_dir) / f"frame-{index:04d}.jpg")
        runner(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                f"{timestamp_seconds:.3f}",
                "-i",
                video_path,
                "-frames:v",
                "1",
                "-vf",
                "scale='min(1600,iw)':-2",
                "-q:v",
                "3",
                output_path,
            ],
            timeout=120,
        )
        keyframes.append(
            VideoKeyframe(
                timestamp_ms=round(timestamp_seconds * 1000),
                frame_index=max(0, round(timestamp_seconds * probe.frame_rate)),
                path=output_path,
            )
        )
    return keyframes


def default_ocr(path: str) -> tuple[str, float | None]:
    try:
        import pytesseract
        from PIL import Image
        from pytesseract import Output

        from app.config import settings

        data = pytesseract.image_to_data(
            Image.open(path), lang=settings.OCR_LANGS, output_type=Output.DICT
        )
        words: list[str] = []
        confidences: list[float] = []
        for text, confidence in zip(data.get("text", []), data.get("conf", [])):
            value = str(text or "").strip()
            try:
                score = float(confidence)
            except (TypeError, ValueError):
                score = -1
            if value and score >= 0:
                words.append(value)
                confidences.append(score / 100)
        return " ".join(words), (
            sum(confidences) / len(confidences) if confidences else None
        )
    except (ImportError, OSError, RuntimeError):
        return "", None


def default_stt(path: str) -> tuple[list[dict[str, Any]], float | None]:
    from app.services.voice_gateway import transcribe_long_interview_chunk

    with open(path, "rb") as stream:
        result = transcribe_long_interview_chunk(
            stream.read(), filename=os.path.basename(path), content_type="audio/mpeg"
        )
    rows = list(result.segments or [])
    if not rows and str(result.text or "").strip():
        rows = [
            {
                "start": 0,
                "end": float(result.duration_seconds or 0),
                "text": result.text,
            }
        ]
    return rows, result.confidence


def detect_first_audio_activity_ms(
    path: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = _run,
) -> int:
    """Return the first non-silent sample offset for timestamp alignment."""

    completed = runner(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            path,
            "-af",
            "silencedetect=noise=-45dB:d=0.1",
            "-f",
            "null",
            "-",
        ],
        timeout=120,
    )
    output = f"{completed.stdout or ''}\n{completed.stderr or ''}"
    start_match = re.search(r"silence_start:\s*([0-9.]+)", output)
    end_match = re.search(r"silence_end:\s*([0-9.]+)", output)
    if not start_match or not end_match or float(start_match.group(1)) > 0.05:
        return 0
    return max(0, round(float(end_match.group(1)) * 1000))


def process_video_file(
    path: str,
    output_dir: str,
    *,
    probe: VideoProbe | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = _run,
    stt: Callable[[str], tuple[list[dict[str, Any]], float | None]] = default_stt,
    ocr: Callable[[str], tuple[str, float | None]] = default_ocr,
) -> VideoProcessingResult:
    from app.config import settings

    probe = probe or probe_video(path, runner=runner)
    audio_paths: list[str] = []
    if probe.has_audio:
        audio_paths = extract_audio_chunks(
            path,
            output_dir,
            chunk_seconds=int(settings.VIDEO_AUDIO_CHUNK_SECONDS),
            runner=runner,
        )
    transcript_segments: list[VideoTranscriptSegment] = []
    for chunk_index, audio_path in enumerate(audio_paths):
        offset_ms = chunk_index * int(settings.VIDEO_AUDIO_CHUNK_SECONDS) * 1000
        rows, confidence = stt(audio_path)
        activity_ms = detect_first_audio_activity_ms(audio_path, runner=runner)
        starts = [
            int(float(row.get("start") or 0) * 1000)
            for row in rows
            if str(row.get("text") or "").strip()
        ]
        first_segment_ms = min(starts) if starts else 0
        # Diarized ASR can partially collapse long leading silence. Align only
        # forward, and only for a material discrepancy, so ordinary word-level
        # timestamp variation is preserved rather than over-corrected.
        activity_shift_ms = (
            activity_ms - first_segment_ms
            if activity_ms - first_segment_ms >= 500
            else 0
        )
        for row in rows:
            text = str(row.get("text") or "").strip()
            if not text:
                continue
            start_ms = (
                offset_ms + activity_shift_ms + int(float(row.get("start") or 0) * 1000)
            )
            end_ms = (
                offset_ms + activity_shift_ms + int(float(row.get("end") or 0) * 1000)
            )
            bounded_start_ms = min(max(0, start_ms), max(0, probe.duration_ms - 1))
            bounded_end_ms = min(
                probe.duration_ms,
                max(bounded_start_ms + 1, end_ms),
            )
            transcript_segments.append(
                VideoTranscriptSegment(
                    start_ms=bounded_start_ms,
                    end_ms=bounded_end_ms,
                    text=text,
                    speaker=str(row.get("speaker") or "").strip() or None,
                    confidence=confidence,
                )
            )

    keyframes = extract_keyframes(path, output_dir, probe, runner=runner)
    for keyframe in keyframes:
        keyframe.ocr_text, keyframe.ocr_confidence = ocr(keyframe.path)
    return VideoProcessingResult(
        probe=probe,
        transcript_segments=transcript_segments,
        keyframes=keyframes,
        audio_chunk_count=len(audio_paths),
    )


def _artifact_hash(*values: Any) -> str:
    payload = json.dumps(values, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _upsert_artifact(
    db: Session,
    revision: AssetRevision,
    *,
    artifact_kind: str,
    content: str | None = None,
    artifact_uri: str | None = None,
    confidence: float | None = None,
    quality_state: str,
    metadata: dict[str, Any] | None = None,
    provider: str = "core.video",
    provider_version: str = "1.0",
) -> DerivedArtifact:
    content_hash = _artifact_hash(content, artifact_uri, metadata or {})
    artifact = (
        db.query(DerivedArtifact)
        .filter(
            DerivedArtifact.tenant_id == revision.tenant_id,
            DerivedArtifact.asset_revision_id == revision.id,
            DerivedArtifact.artifact_kind == artifact_kind,
            DerivedArtifact.provider == provider,
            DerivedArtifact.provider_version == provider_version,
            DerivedArtifact.content_hash == content_hash,
        )
        .first()
    )
    if artifact is None:
        artifact = DerivedArtifact(
            tenant_id=revision.tenant_id,
            asset_revision_id=revision.id,
            artifact_kind=artifact_kind,
            content_hash=content_hash,
            provider=provider,
            provider_version=provider_version,
            quality_state=quality_state,
            confidence=confidence,
            content=content,
            artifact_uri=artifact_uri,
            metadata_json=dict(metadata or {}),
        )
        db.add(artifact)
        db.flush()
    return artifact


def _ensure_video_evidence(
    db: Session,
    revision: AssetRevision,
    artifact: DerivedArtifact,
    *,
    start_ms: int,
    end_ms: int | None = None,
    frame_index: int | None = None,
    speaker: str | None = None,
) -> EvidenceSpan:
    safe_end = max(start_ms + 1, int(end_ms or start_ms + 1))
    evidence = (
        db.query(EvidenceSpan)
        .filter(
            EvidenceSpan.tenant_id == revision.tenant_id,
            EvidenceSpan.artifact_id == artifact.id,
            EvidenceSpan.asset_revision_id == revision.id,
            EvidenceSpan.locator_kind == "video",
            EvidenceSpan.start_ms == start_ms,
            EvidenceSpan.end_ms == safe_end,
            EvidenceSpan.frame_index == frame_index,
        )
        .first()
    )
    if evidence is None:
        evidence = EvidenceSpan(
            tenant_id=revision.tenant_id,
            artifact_id=artifact.id,
            asset_revision_id=revision.id,
            locator_kind="video",
            start_ms=start_ms,
            end_ms=safe_end,
            frame_index=frame_index,
            speaker=speaker,
            track_id="video:0",
        )
        db.add(evidence)
        db.flush()
    return evidence


def project_video_result(
    db: Session,
    revision: AssetRevision,
    result: VideoProcessingResult,
    *,
    create_procedure_candidate: bool = True,
) -> dict[str, Any]:
    """Idempotently project processing output and a review-gated procedure."""

    _upsert_artifact(
        db,
        revision,
        artifact_kind="audio_event",
        content=json.dumps(
            {
                "event": "audio_demuxed",
                "chunk_count": result.audio_chunk_count,
                "retained": False,
            },
            ensure_ascii=False,
        ),
        quality_state="ready",
        metadata={"ephemeral_processing": True},
    )

    transcript_artifacts: list[DerivedArtifact] = []
    for segment in result.transcript_segments:
        artifact = _upsert_artifact(
            db,
            revision,
            artifact_kind="transcript_segment",
            content=segment.text,
            confidence=segment.confidence,
            quality_state="review_required",
            metadata={
                "start_ms": segment.start_ms,
                "end_ms": segment.end_ms,
                "speaker": segment.speaker,
            },
        )
        _ensure_video_evidence(
            db,
            revision,
            artifact,
            start_ms=segment.start_ms,
            end_ms=segment.end_ms,
            speaker=segment.speaker,
        )
        transcript_artifacts.append(artifact)

    keyframe_artifacts: list[DerivedArtifact] = []
    ocr_artifacts: list[DerivedArtifact] = []
    for keyframe in result.keyframes:
        artifact = _upsert_artifact(
            db,
            revision,
            artifact_kind="keyframe",
            artifact_uri=keyframe.artifact_uri,
            quality_state="ready",
            metadata={
                "timestamp_ms": keyframe.timestamp_ms,
                "frame_index": keyframe.frame_index,
                "storage_key": keyframe.storage_key,
            },
        )
        _ensure_video_evidence(
            db,
            revision,
            artifact,
            start_ms=keyframe.timestamp_ms,
            frame_index=keyframe.frame_index,
        )
        keyframe_artifacts.append(artifact)
        if keyframe.ocr_text.strip():
            ocr_artifact = _upsert_artifact(
                db,
                revision,
                artifact_kind="ocr_region",
                content=keyframe.ocr_text.strip(),
                confidence=keyframe.ocr_confidence,
                quality_state="review_required",
                metadata={
                    "timestamp_ms": keyframe.timestamp_ms,
                    "frame_index": keyframe.frame_index,
                    "keyframe_artifact_id": str(artifact.id),
                },
            )
            _ensure_video_evidence(
                db,
                revision,
                ocr_artifact,
                start_ms=keyframe.timestamp_ms,
                frame_index=keyframe.frame_index,
            )
            ocr_artifacts.append(ocr_artifact)

    step_sources: list[dict[str, Any]] = [
        {
            "text": segment.text,
            "start_ms": segment.start_ms,
            "end_ms": segment.end_ms,
            "evidence_artifact_id": str(artifact.id),
        }
        for segment, artifact in zip(result.transcript_segments, transcript_artifacts)
        if segment.text.strip()
    ]
    if not step_sources:
        step_sources = [
            {
                "text": artifact.content,
                "start_ms": int(
                    (artifact.metadata_json or {}).get("timestamp_ms") or 0
                ),
                "end_ms": int((artifact.metadata_json or {}).get("timestamp_ms") or 0)
                + 1,
                "evidence_artifact_id": str(artifact.id),
            }
            for artifact in ocr_artifacts
            if str(artifact.content or "").strip()
        ]
    procedure = None
    if step_sources and create_procedure_candidate:
        procedure_payload = {
            "schema_version": "1.0",
            "title": "影片作業程序候選",
            "summary": "由影片逐字稿與關鍵畫面自動整理，核准前不可用於正式回答。",
            "steps": [
                {
                    "sequence": index,
                    **step,
                    "deep_link": (
                        f"/knowledge/videos/{revision.asset_id}?t={step['start_ms']}"
                    ),
                }
                for index, step in enumerate(step_sources[:30], start=1)
            ],
        }
        procedure = _upsert_artifact(
            db,
            revision,
            artifact_kind="procedure_candidate",
            content=json.dumps(procedure_payload, ensure_ascii=False),
            quality_state="review_required",
            metadata={"step_count": len(procedure_payload["steps"])},
        )
        _ensure_video_evidence(
            db,
            revision,
            procedure,
            start_ms=int(step_sources[0]["start_ms"]),
            end_ms=int(step_sources[-1]["end_ms"]),
        )

    return {
        "transcript_count": len(transcript_artifacts),
        "keyframe_count": len(keyframe_artifacts),
        "ocr_count": len(ocr_artifacts),
        "procedure_artifact_id": str(procedure.id) if procedure else None,
    }
