"""Audio precision pipeline primitives (AV2).

The module is provider-neutral: it prepares a lossless, speech-focused working
copy, plans bounded overlapping chunks, merges duplicate boundary text and
records every normalization/correction separately from raw ASR output.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


Runner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class AudioQualityProfile:
    duration_ms: int
    sample_rate: int
    channels: int
    mean_volume_db: float | None
    peak_volume_db: float | None
    silence_ratio: float
    clipped: bool
    low_volume: bool
    risks: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "duration_ms": self.duration_ms,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "mean_volume_db": self.mean_volume_db,
            "peak_volume_db": self.peak_volume_db,
            "silence_ratio": self.silence_ratio,
            "clipped": self.clipped,
            "low_volume": self.low_volume,
            "risks": list(self.risks),
        }


@dataclass(frozen=True)
class AudioChunkPlan:
    index: int
    start_ms: int
    end_ms: int
    overlap_before_ms: int = 0
    overlap_after_ms: int = 0

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


@dataclass(frozen=True)
class TranscriptCandidate:
    start_ms: int
    end_ms: int
    text: str
    speaker: str | None = None
    confidence: float | None = None
    source_pass: str = "A"
    critical_tokens: tuple[str, ...] = ()
    corrections: tuple[dict[str, str], ...] = ()


def parse_audio_analysis(
    output: str, *, duration_ms: int, sample_rate: int, channels: int
) -> AudioQualityProfile:
    mean_match = re.search(r"mean_volume:\s*(-?[0-9.]+)\s*dB", output)
    peak_match = re.search(r"max_volume:\s*(-?[0-9.]+)\s*dB", output)
    silence_durations = [
        float(value) for value in re.findall(r"silence_duration:\s*([0-9.]+)", output)
    ]
    mean_db = float(mean_match.group(1)) if mean_match else None
    peak_db = float(peak_match.group(1)) if peak_match else None
    silence_ratio = min(1.0, sum(silence_durations) * 1000 / max(1, duration_ms))
    clipped = peak_db is not None and peak_db >= -0.1
    low_volume = mean_db is not None and mean_db < -32.0
    risks: list[str] = []
    if clipped:
        risks.append("clipping")
    if low_volume:
        risks.append("low_volume")
    if silence_ratio >= 0.6:
        risks.append("mostly_silence")
    if sample_rate < 16_000:
        risks.append("low_sample_rate")
    return AudioQualityProfile(
        duration_ms=duration_ms,
        sample_rate=sample_rate,
        channels=channels,
        mean_volume_db=mean_db,
        peak_volume_db=peak_db,
        silence_ratio=round(silence_ratio, 4),
        clipped=clipped,
        low_volume=low_volume,
        risks=tuple(risks),
    )


def analyze_audio_quality(
    source_path: str,
    *,
    duration_ms: int,
    sample_rate: int,
    channels: int,
    runner: Runner,
) -> AudioQualityProfile:
    completed = runner(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            source_path,
            "-af",
            "volumedetect,silencedetect=noise=-42dB:d=0.35",
            "-f",
            "null",
            "-",
        ],
        timeout=3600,
    )
    return parse_audio_analysis(
        f"{completed.stdout or ''}\n{completed.stderr or ''}",
        duration_ms=duration_ms,
        sample_rate=sample_rate,
        channels=channels,
    )


def create_lossless_working_copy(
    source_path: str,
    output_path: str,
    *,
    profile: AudioQualityProfile,
    runner: Runner,
) -> str:
    filters = ["highpass=f=70", "lowpass=f=7600"]
    if profile.low_volume and not profile.clipped:
        filters.append("loudnorm=I=-20:TP=-2:LRA=11")
    runner(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            source_path,
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-af",
            ",".join(filters),
            "-c:a",
            "pcm_s16le",
            output_path,
        ],
        timeout=3600,
    )
    path = Path(output_path)
    if not path.is_file() or path.stat().st_size <= 44:
        raise RuntimeError("lossless audio working copy was not created")
    return output_path


def build_adaptive_chunk_plan(
    duration_ms: int,
    *,
    speech_intervals: list[tuple[int, int]] | None = None,
    target_ms: int = 75_000,
    maximum_ms: int = 90_000,
    overlap_ms: int = 1_500,
) -> list[AudioChunkPlan]:
    if duration_ms <= 0 or target_ms <= overlap_ms or maximum_ms < target_ms:
        raise ValueError("invalid adaptive audio chunk bounds")
    speech_intervals = speech_intervals or [(0, duration_ms)]
    cut_candidates = sorted(
        {
            0,
            duration_ms,
            *(end for _start, end in speech_intervals if 0 < end < duration_ms),
        }
    )
    chunks: list[AudioChunkPlan] = []
    start = 0
    while start < duration_ms:
        target = min(duration_ms, start + target_ms)
        hard_end = min(duration_ms, start + maximum_ms)
        candidates = [
            point for point in cut_candidates if start + 10_000 <= point <= hard_end
        ]
        end = (
            min(candidates, key=lambda point: abs(point - target))
            if candidates
            else hard_end
        )
        if end <= start:
            end = hard_end
        actual_start = max(0, start - (overlap_ms if chunks else 0))
        actual_end = min(duration_ms, end + (overlap_ms if end < duration_ms else 0))
        chunks.append(
            AudioChunkPlan(
                index=len(chunks),
                start_ms=actual_start,
                end_ms=actual_end,
                overlap_before_ms=start - actual_start,
                overlap_after_ms=actual_end - end,
            )
        )
        start = end
    return chunks


def extract_lossless_chunks(
    working_copy: str,
    output_dir: str,
    plans: list[AudioChunkPlan],
    *,
    runner: Runner,
) -> list[str]:
    paths: list[str] = []
    for plan in plans:
        output_path = str(Path(output_dir) / f"precision-{plan.index:05d}.wav")
        runner(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                f"{plan.start_ms / 1000:.3f}",
                "-i",
                working_copy,
                "-t",
                f"{plan.duration_ms / 1000:.3f}",
                "-c:a",
                "pcm_s16le",
                output_path,
            ],
            timeout=600,
        )
        paths.append(output_path)
    return paths


def extract_critical_tokens(
    text: str, glossary: list[str] | None = None
) -> tuple[str, ...]:
    candidates = set()
    lowered = text.lower()
    for term in glossary or []:
        if term and term.lower() in lowered:
            candidates.add(term)
    candidates.update(
        re.findall(r"\b[A-Z]{1,8}[-_ ]?\d{2,}[A-Z0-9_-]*\b", text, flags=re.I)
    )
    candidates.update(
        re.findall(
            r"(?<!\d)\d+(?:\.\d+)?\s*(?:MPa|kPa|bar|kg|mm|°C|V|A|元|萬|%)",
            text,
            flags=re.I,
        )
    )
    return tuple(sorted(candidates, key=str.lower))


def correct_with_approved_glossary(
    text: str, corrections: dict[str, str]
) -> tuple[str, tuple[dict[str, str], ...]]:
    """Only deterministic, tenant-approved substitutions; never silent LLM rewriting."""
    corrected = text
    applied: list[dict[str, str]] = []
    for wrong, right in corrections.items():
        if wrong and wrong in corrected and wrong != right:
            corrected = corrected.replace(wrong, right)
            applied.append({"from": wrong, "to": right, "method": "approved_glossary"})
    return corrected, tuple(applied)


def merge_overlapping_candidates(
    candidates: list[TranscriptCandidate],
) -> list[TranscriptCandidate]:
    """Remove overlap duplicates while preserving source time and correction lineage."""
    ordered = sorted(candidates, key=lambda item: (item.start_ms, item.end_ms))
    merged: list[TranscriptCandidate] = []
    for item in ordered:
        if not item.text.strip():
            continue
        if merged:
            previous = merged[-1]
            overlap = max(
                0,
                min(previous.end_ms, item.end_ms)
                - max(previous.start_ms, item.start_ms),
            )
            normalized_previous = "".join(previous.text.lower().split())
            normalized_current = "".join(item.text.lower().split())
            duplicate = overlap > 0 and (
                normalized_current in normalized_previous
                or normalized_previous in normalized_current
            )
            if duplicate:
                preferred = item if len(item.text) > len(previous.text) else previous
                merged[-1] = TranscriptCandidate(
                    start_ms=min(previous.start_ms, item.start_ms),
                    end_ms=max(previous.end_ms, item.end_ms),
                    text=preferred.text,
                    speaker=preferred.speaker,
                    confidence=preferred.confidence,
                    source_pass=preferred.source_pass,
                    critical_tokens=tuple(
                        sorted(set(previous.critical_tokens + item.critical_tokens))
                    ),
                    corrections=previous.corrections + item.corrections,
                )
                continue
        merged.append(item)
    return merged


def needs_precision_pass(
    candidate: TranscriptCandidate, profile: AudioQualityProfile
) -> bool:
    return bool(
        profile.risks
        or candidate.confidence is None
        or candidate.confidence < 0.75
        or candidate.critical_tokens
        or re.search(r"(?:\b\w+\b)(?:\s+\1){2,}", candidate.text, flags=re.I)
    )


def precision_candidate_from_passes(
    *,
    plan: AudioChunkPlan,
    pass_a_text: str,
    pass_b_text: str,
    speaker: str | None,
    glossary: list[str] | None = None,
) -> TranscriptCandidate:
    """Keep Pass B as an explicit candidate and describe divergence."""
    a = " ".join(pass_a_text.split())
    b = " ".join(pass_b_text.split())
    changes: tuple[dict[str, str], ...] = ()
    chosen = a
    source_pass = "A"
    if b and b != a:
        chosen = b
        source_pass = "B_candidate"
        changes = ({"from": a, "to": b, "method": "contextual_asr_candidate"},)
    return TranscriptCandidate(
        start_ms=plan.start_ms,
        end_ms=plan.end_ms,
        text=chosen,
        speaker=speaker,
        confidence=None,
        source_pass=source_pass,
        critical_tokens=extract_critical_tokens(chosen, glossary),
        corrections=changes,
    )
