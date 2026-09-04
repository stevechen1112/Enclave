"""Probe Input I5 corpus and emit an honest codec/timeline evidence report."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.media_quality import (
    TimelineObservation,
    evaluate_media_matrix,
    evaluate_timeline_alignment,
)
from app.services.input_quality import assess_evidence_claim


def probe(path: Path) -> dict:
    completed = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_streams", "-show_format",
            "-of", "json", str(path),
        ],
        check=True, capture_output=True, text=True, timeout=120,
    )
    payload = json.loads(completed.stdout)
    streams = list(payload.get("streams") or [])
    return {
        "extension": path.suffix.lower(),
        "filename": path.name,
        "status": "PASS" if streams else "FAIL",
        "format_name": (payload.get("format") or {}).get("format_name"),
        "duration_seconds": float((payload.get("format") or {}).get("duration") or 0),
        "codecs": [row.get("codec_name") for row in streams],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", default="artifacts/input/i5_corpus")
    parser.add_argument("--report", default="artifacts/input/i5_media_report.json")
    args = parser.parse_args()
    corpus = Path(args.corpus)
    rows = [probe(path) for path in sorted(corpus.iterdir()) if path.suffix.lower() in {
        ".mp3", ".wav", ".m4a", ".ogg", ".flac", ".mp4", ".mov", ".webm", ".mkv"
    }]
    audio_matrix = evaluate_media_matrix(
        [row for row in rows if row["extension"] in {".mp3", ".wav", ".m4a", ".ogg", ".flac"}],
        required_extensions={".mp3", ".wav", ".m4a", ".ogg", ".flac"},
    )
    video_matrix = evaluate_media_matrix(
        [row for row in rows if row["extension"] in {".mp4", ".mov", ".webm", ".mkv"}],
        required_extensions={".mp4", ".mov", ".webm", ".mkv"},
    )
    timeline_alignment = evaluate_timeline_alignment(
        [
            TimelineObservation(
                expected_start_ms=0,
                actual_start_ms=0,
                expected_end_ms=(
                    12_000
                    if row["extension"]
                    in {".mp3", ".wav", ".m4a", ".ogg", ".flac"}
                    else 18_000
                ),
                actual_end_ms=round(row["duration_seconds"] * 1000),
            )
            for row in rows
        ],
        maximum_mean_error_ms=100,
    )
    execution_status = (
        "PASS"
        if audio_matrix["status"] == video_matrix["status"] == "PASS"
        and timeline_alignment["status"] == "PASS"
        else "FAIL"
    )
    declared_gaps = [
        "24-hour queue degradation campaign not run",
        "physical-device samples not supplied",
        "licensed factory speech ground truth not supplied",
    ]
    report = {
        "schema_version": "input-i5-evidence.v1",
        "execution_status": execution_status,
        "certification": assess_evidence_claim(
            evidence_class="synthetic",
            execution_status=execution_status,
            requested_claim="semantic",
            ground_truth_verified=False,
            declared_gaps=declared_gaps,
        ),
        "audio_matrix": audio_matrix,
        "video_matrix": video_matrix,
        "timeline_alignment": timeline_alignment,
        "queue_degradation_24h": {
            "status": "NOT_RUN",
            "reason": "requires a dedicated live worker/storage/provider campaign",
        },
        "device_origin": {"status": "PENDING", "reason": "physical-device samples not supplied"},
        "speech_quality": {"status": "PENDING", "reason": "licensed factory speech ground truth not supplied"},
    }
    target = Path(args.report)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if execution_status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
