"""Bounded long-media helpers used by Input I5 workers.

The helpers only operate on local temporary files. Originals remain in object
storage, which makes processing retries independent from the browser upload.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class MediaPolicyError(ValueError):
    """A deterministic media rejection that retries cannot repair."""

    retryable = False

    def __init__(
        self,
        message: str,
        *,
        code: str = "media_policy_rejected",
        user_message: str = "此媒體格式目前無法處理，請轉換格式後重新上傳。",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.user_message = user_message


Runner = Callable[..., subprocess.CompletedProcess[str]]


def run_media_command(
    command: list[str], *, timeout: int = 300
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


@dataclass(frozen=True)
class AudioProbe:
    duration_ms: int
    codec: str
    format_name: str
    sample_rate: int
    channels: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "duration_ms": self.duration_ms,
            "codec": self.codec,
            "format_name": self.format_name,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
        }


def parse_audio_probe_payload(payload: dict[str, Any]) -> AudioProbe:
    streams = list(payload.get("streams") or [])
    audio = next(
        (row for row in streams if row.get("codec_type") == "audio"), None
    )
    if audio is None:
        raise MediaPolicyError("audio stream not found")
    format_data = dict(payload.get("format") or {})
    try:
        duration_ms = round(
            float(format_data.get("duration") or audio.get("duration") or 0) * 1000
        )
        sample_rate = int(audio.get("sample_rate") or 0)
        channels = int(audio.get("channels") or 0)
    except (TypeError, ValueError) as exc:
        raise MediaPolicyError("audio metadata is invalid") from exc
    probe = AudioProbe(
        duration_ms=duration_ms,
        codec=str(audio.get("codec_name") or "").lower(),
        format_name=str(format_data.get("format_name") or "").lower(),
        sample_rate=sample_rate,
        channels=channels,
    )
    if probe.duration_ms <= 0 or not probe.codec:
        raise MediaPolicyError("audio metadata is incomplete")
    return probe


def validate_audio_probe(probe: AudioProbe) -> None:
    from app.config import settings

    codecs = {
        item.strip().lower()
        for item in str(settings.AUDIO_ALLOWED_CODECS or "").split(",")
        if item.strip()
    }
    if probe.codec not in codecs:
        raise MediaPolicyError(
            f"unsupported audio codec: {probe.codec}",
            code="unsupported_audio_codec",
            user_message=f"此音檔使用尚未支援的編碼（{probe.codec}），請轉換後重新上傳。",
        )
    if probe.duration_ms > int(settings.AUDIO_MAX_SECONDS) * 1000:
        raise MediaPolicyError(
            "audio duration exceeds tenant-safe limit",
            code="audio_duration_exceeded",
            user_message="音檔長度超過目前允許上限，請分段後重新上傳。",
        )


def probe_audio(path: str, *, runner: Runner = run_media_command) -> AudioProbe:
    completed = runner(
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
        probe = parse_audio_probe_payload(json.loads(completed.stdout))
    except (TypeError, json.JSONDecodeError) as exc:
        raise MediaPolicyError("ffprobe returned invalid audio metadata") from exc
    validate_audio_probe(probe)
    return probe


def extract_audio_chunks(
    source_path: str,
    output_dir: str,
    *,
    chunk_seconds: int,
    runner: Runner = run_media_command,
) -> list[str]:
    from app.config import settings

    if chunk_seconds < 10:
        raise MediaPolicyError("audio chunk duration is below safe minimum")
    pattern = str(Path(output_dir) / "audio-%05d.mp3")
    runner(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-threads",
            str(max(1, int(settings.MEDIA_PROCESSING_THREADS))),
            "-i",
            source_path,
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
        timeout=3600,
    )
    return [str(path) for path in sorted(Path(output_dir).glob("audio-*.mp3"))]


def create_browser_video_proxy(
    source_path: str,
    output_path: str,
    *,
    runner: Runner = run_media_command,
) -> str:
    """Create bounded H.264/AAC MP4 with fast-start for browser review."""

    from app.config import settings

    width = max(320, int(settings.MEDIA_PROXY_MAX_WIDTH))
    runner(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-threads",
            str(max(1, int(settings.MEDIA_PROCESSING_THREADS))),
            "-filter_threads",
            str(max(1, int(settings.MEDIA_PROCESSING_THREADS))),
            "-i",
            source_path,
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-vf",
            f"scale='min({width},iw)':-2",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-b:v",
            str(settings.MEDIA_PROXY_VIDEO_BITRATE),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            "-movflags",
            "+faststart",
            output_path,
        ],
        timeout=3600,
    )
    if not Path(output_path).is_file() or Path(output_path).stat().st_size <= 0:
        raise MediaPolicyError("video proxy was not created")
    return output_path


def create_browser_audio_proxy(
    source_path: str,
    output_path: str,
    *,
    runner: Runner = run_media_command,
) -> str:
    """Create a broadly supported, bounded MP3 review proxy."""

    from app.config import settings

    runner(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-threads",
            str(max(1, int(settings.MEDIA_PROCESSING_THREADS))),
            "-i",
            source_path,
            "-vn",
            "-ac",
            "1",
            "-ar",
            "44100",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "96k",
            output_path,
        ],
        timeout=3600,
    )
    if not Path(output_path).is_file() or Path(output_path).stat().st_size <= 0:
        raise MediaPolicyError("audio proxy was not created")
    return output_path
