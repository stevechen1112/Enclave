from __future__ import annotations

from PIL import Image

from app.services.video_adaptive_sampling import (
    OCRObservation,
    build_ocr_tracks,
    frame_features,
    scan_fps_for,
    select_keyframes,
)
from app.services.video_processing import VideoProbe


def _probe(seconds: int, fps: float = 30) -> VideoProbe:
    return VideoProbe(seconds * 1000, 1920, 1080, "h264", "aac", fps, "mp4")


def test_scan_rate_is_adaptive_and_bounded():
    assert scan_fps_for(_probe(60)) == 4.0
    assert scan_fps_for(_probe(3600)) == 0.2
    assert scan_fps_for(_probe(60, fps=2)) == 2


def test_duplicate_frames_are_not_selected(tmp_path):
    paths = []
    for index, color in enumerate(("white", "white", "black")):
        path = tmp_path / f"{index}.jpg"
        Image.new("RGB", (64, 64), color).save(path)
        paths.append(path)
    features = []
    previous = None
    for index, path in enumerate(paths):
        item = frame_features(str(path), index * 1000, index * 30, previous)
        previous = item.perceptual_hash
        features.append(item)
    selected = select_keyframes(features, maximum=3)
    assert len(selected) < 3


def test_repeated_ocr_is_merged_into_time_track():
    tracks = build_ocr_tracks(
        [
            OCRObservation(0, "壓力 2.5 MPa", (0.1, 0.1, 0.5, 0.2), 0.9),
            OCRObservation(2000, "壓力 2.5 MPa", (0.1, 0.1, 0.5, 0.2), 0.8),
            OCRObservation(8000, "溫度 80 °C", None, 0.95),
        ]
    )
    assert len(tracks) == 2
    assert tracks[0].observation_count == 2
    assert tracks[0].start_ms == 0
