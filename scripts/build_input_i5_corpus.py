"""Build a deterministic, non-customer Input I5 codec and noise corpus.

Requires ffmpeg on PATH. The resulting samples prove container/codec and
timeline mechanics only; they do not substitute for licensed human speech or
physical-device acceptance samples.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def run(command: list[str]) -> None:
    subprocess.run(command, check=True, capture_output=True, text=True, timeout=900)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="artifacts/input/i5_corpus")
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    audio_specs = {
        "machine-noise.mp3": ["-c:a", "libmp3lame"],
        "inspection.wav": ["-c:a", "pcm_s16le"],
        "handover.m4a": ["-c:a", "aac"],
        "low-quality.ogg": ["-c:a", "libvorbis", "-ar", "8000"],
        "lossless.flac": ["-c:a", "flac"],
    }
    for filename, codec in audio_specs.items():
        run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=12",
            "-f", "lavfi", "-i", "anoisesrc=color=pink:duration=12:amplitude=0.08",
            "-filter_complex", "[0:a][1:a]amix=inputs=2:weights=1 0.25",
            *codec, str(output / filename),
        ])

    video_specs = {
        "machine-sop.mp4": ["-c:v", "libx264", "-c:a", "aac"],
        "phone-export.mov": ["-c:v", "libx264", "-c:a", "aac"],
        "browser-capture.webm": ["-c:v", "libvpx-vp9", "-c:a", "libopus"],
        "camera-export.mkv": ["-c:v", "libx264", "-c:a", "aac"],
    }
    for filename, codecs in video_specs.items():
        run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=15:duration=18",
            "-f", "lavfi", "-i", "sine=frequency=220:duration=18",
            *codecs, "-pix_fmt", "yuv420p", "-shortest", str(output / filename),
        ])

    rows = []
    for path in sorted(output.iterdir()):
        if path.is_file() and path.name != "manifest.json":
            rows.append({
                "filename": path.name,
                "extension": path.suffix.lower(),
                "byte_size": path.stat().st_size,
                "sha256": sha256(path),
                "classification": "synthetic_signal",
            })
    manifest = {
        "schema_version": "input-i5-corpus.v1",
        "claim_scope": "container_codec_timeline_mechanics_only",
        "excluded_claims": [
            "physical_device_origin",
            "accent_accuracy",
            "factory_speech_asr_accuracy",
            "cross_industry_action_or_anomaly_accuracy",
        ],
        "files": rows,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
