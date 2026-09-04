"""Bounded adaptive video sampling and OCR-track construction (AV3)."""

from __future__ import annotations

import math
import re
import subprocess
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable

from PIL import Image, ImageFilter, ImageStat

from app.services.video_processing import VideoKeyframe, VideoProbe


Runner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class FrameFeatures:
    path: str
    timestamp_ms: int
    frame_index: int
    perceptual_hash: int
    blur_score: float
    brightness: float
    visual_change: float
    text_change: float = 0.0
    scene_score: float = 0.0

    @property
    def selection_score(self) -> float:
        quality = min(1.0, self.blur_score / 120.0)
        exposure = 1.0 if 25 <= self.brightness <= 235 else 0.25
        return (
            self.scene_score * 0.35
            + self.visual_change * 0.30
            + self.text_change * 0.25
            + quality * exposure * 0.10
        )


@dataclass(frozen=True)
class OCRObservation:
    timestamp_ms: int
    text: str
    bbox: tuple[float, float, float, float] | None
    confidence: float | None


@dataclass(frozen=True)
class OCRTrack:
    track_id: str
    start_ms: int
    end_ms: int
    text: str
    bbox: tuple[float, float, float, float] | None
    confidence: float | None
    observation_count: int


def classify_video_profile(probe: VideoProbe) -> str:
    if probe.frame_rate <= 8:
        return "screen_or_slides"
    if probe.duration_ms >= 30 * 60 * 1000:
        return "long_form"
    if probe.width >= probe.height * 1.7:
        return "landscape_operation"
    return "handheld_or_portrait"


def scan_fps_for(
    probe: VideoProbe, *, minimum: float = 0.2, maximum: float = 4.0
) -> float:
    duration_seconds = probe.duration_ms / 1000
    if duration_seconds <= 120:
        desired = 4.0
    elif duration_seconds <= 600:
        desired = 1.0
    elif duration_seconds <= 1800:
        desired = 0.5
    else:
        desired = 0.2
    return max(minimum, min(maximum, desired, max(probe.frame_rate, minimum)))


def _dhash(image: Image.Image) -> int:
    sample = image.convert("L").resize((9, 8))
    pixels = list(
        sample.get_flattened_data()
        if hasattr(sample, "get_flattened_data")
        else sample.getdata()
    )
    value = 0
    for y in range(8):
        for x in range(8):
            value = (value << 1) | (pixels[y * 9 + x] > pixels[y * 9 + x + 1])
    return value


def _hamming(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def frame_features(
    path: str, timestamp_ms: int, frame_index: int, previous_hash: int | None
) -> FrameFeatures:
    with Image.open(path) as source:
        image = source.convert("RGB")
        grayscale = image.convert("L")
        edge_variance = ImageStat.Stat(grayscale.filter(ImageFilter.FIND_EDGES)).var[0]
        brightness = ImageStat.Stat(grayscale).mean[0]
        image_hash = _dhash(image)
    visual_change = (
        1.0 if previous_hash is None else _hamming(previous_hash, image_hash) / 64
    )
    return FrameFeatures(
        path=path,
        timestamp_ms=timestamp_ms,
        frame_index=frame_index,
        perceptual_hash=image_hash,
        blur_score=float(edge_variance),
        brightness=float(brightness),
        visual_change=visual_change,
    )


def select_keyframes(
    candidates: list[FrameFeatures], *, maximum: int, dedupe_distance: int = 5
) -> list[FrameFeatures]:
    if maximum <= 0:
        return []
    mandatory = candidates[:1] + candidates[-1:] if candidates else []
    ranked = sorted(
        candidates, key=lambda item: (-item.selection_score, item.timestamp_ms)
    )
    selected: list[FrameFeatures] = []
    for candidate in [*mandatory, *ranked]:
        if any(candidate.path == row.path for row in selected):
            continue
        if any(
            _hamming(candidate.perceptual_hash, row.perceptual_hash) <= dedupe_distance
            for row in selected
        ):
            continue
        selected.append(candidate)
        if len(selected) >= maximum:
            break
    return sorted(selected, key=lambda item: item.timestamp_ms)


def extract_adaptive_keyframes(
    video_path: str,
    output_dir: str,
    probe: VideoProbe,
    *,
    maximum_selected: int,
    maximum_scan_frames: int = 1500,
    minimum_fps: float = 0.2,
    maximum_fps: float = 4.0,
    runner: Runner,
) -> list[VideoKeyframe]:
    fps = scan_fps_for(probe, minimum=minimum_fps, maximum=maximum_fps)
    duration_seconds = probe.duration_ms / 1000
    if math.ceil(duration_seconds * fps) > maximum_scan_frames:
        fps = max(minimum_fps, maximum_scan_frames / max(duration_seconds, 1))
    pattern = str(Path(output_dir) / "scan-%06d.jpg")
    runner(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            video_path,
            "-vf",
            f"fps={fps:.6f},scale='min(1280,iw)':-2",
            "-q:v",
            "5",
            pattern,
        ],
        timeout=3600,
    )
    features: list[FrameFeatures] = []
    previous_hash: int | None = None
    for index, path in enumerate(sorted(Path(output_dir).glob("scan-*.jpg"))):
        timestamp_ms = min(probe.duration_ms - 1, round(index * 1000 / fps))
        item = frame_features(
            str(path),
            timestamp_ms,
            round(timestamp_ms * probe.frame_rate / 1000),
            previous_hash,
        )
        features.append(item)
        previous_hash = item.perceptual_hash
    selected = select_keyframes(features, maximum=maximum_selected)
    return [
        VideoKeyframe(item.timestamp_ms, item.frame_index, item.path)
        for item in selected
    ]


def normalize_ocr_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def build_ocr_tracks(
    observations: list[OCRObservation],
    *,
    maximum_gap_ms: int = 5_000,
    similarity_min: float = 0.86,
) -> list[OCRTrack]:
    tracks: list[list[OCRObservation]] = []
    for observation in sorted(observations, key=lambda item: item.timestamp_ms):
        text = normalize_ocr_text(observation.text)
        if not text:
            continue
        target = None
        for track in reversed(tracks):
            last = track[-1]
            if observation.timestamp_ms - last.timestamp_ms > maximum_gap_ms:
                break
            if (
                SequenceMatcher(
                    None, normalize_ocr_text(last.text).lower(), text.lower()
                ).ratio()
                >= similarity_min
            ):
                target = track
                break
        if target is None:
            tracks.append([observation])
        else:
            target.append(observation)
    results: list[OCRTrack] = []
    for index, track in enumerate(tracks):
        best = max(track, key=lambda item: (item.confidence or 0, len(item.text)))
        confidences = [item.confidence for item in track if item.confidence is not None]
        results.append(
            OCRTrack(
                track_id=f"ocr-{index:05d}",
                start_ms=track[0].timestamp_ms,
                end_ms=max(track[-1].timestamp_ms + 1, track[0].timestamp_ms + 1),
                text=normalize_ocr_text(best.text),
                bbox=best.bbox,
                confidence=sum(confidences) / len(confidences) if confidences else None,
                observation_count=len(track),
            )
        )
    return results
