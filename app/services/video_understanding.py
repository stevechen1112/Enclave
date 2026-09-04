"""Fail-closed multi-modal timeline providers and artifact projection.

Built-in providers only claim what they can prove from the source.  Speaker
labels are projected when supplied by the configured ASR/diarization service;
they are never invented.  Audio anomaly recognition remains explicitly
unavailable until a tenant-approved specialist provider is registered.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
from array import array
from dataclasses import dataclass, field
from statistics import median
from typing import Any

from sqlalchemy.orm import Session

from app.models.asset import AssetRevision, DerivedArtifact
from app.platform.multimodal import (
    MultimodalAnalysisContext,
    MultimodalProviderOutput,
    MultimodalUnderstandingProvider,
    TimelineObservation,
)
from app.services.video_processing import (
    VideoProcessingResult,
    _ensure_video_evidence,
    _upsert_artifact,
)

logger = logging.getLogger(__name__)

_CAPABILITIES = (
    "speaker_diarization",
    "scene_segmentation",
    "action_event",
    "equipment_state",
    "audio_anomaly",
    "temporal_alignment",
)


@dataclass
class MultimodalUnderstandingResult:
    observations: list[TimelineObservation] = field(default_factory=list)
    capability_states: dict[str, str] = field(default_factory=dict)
    provider_failures: list[dict[str, str]] = field(default_factory=list)


def parse_scene_showinfo(
    stderr: str, *, duration_ms: int, frame_rate: float
) -> list[TimelineObservation]:
    points = sorted(
        {
            max(0, min(duration_ms - 1, round(float(value) * 1000)))
            for value in re.findall(r"pts_time:([0-9]+(?:\.[0-9]+)?)", stderr or "")
        }
    )
    boundaries = [0, *[point for point in points if point > 0]]
    rows: list[TimelineObservation] = []
    for index, start_ms in enumerate(boundaries):
        end_ms = boundaries[index + 1] if index + 1 < len(boundaries) else duration_ms
        if end_ms <= start_ms:
            continue
        rows.append(
            TimelineObservation(
                kind="video_scene",
                start_ms=start_ms,
                end_ms=end_ms,
                frame_index=max(0, round((start_ms / 1000) * frame_rate)),
                label=f"scene_{index + 1}",
                content=f"鏡頭 {index + 1}",
                confidence=None,
                provider="core.ffmpeg_scene",
                provider_version="1.0",
                attributes={"boundary_method": "ffmpeg_scene_score", "threshold": 0.35},
            )
        )
    return rows


class FfmpegSceneProvider:
    provider_key = "core.ffmpeg_scene"
    provider_version = "1.0"
    capability_keys = ("scene_segmentation",)
    execution_boundary = "local_ffmpeg"

    def __init__(self, runner: Any | None = None) -> None:
        self._runner = runner or subprocess.run

    def analyze(self, context: MultimodalAnalysisContext) -> MultimodalProviderOutput:
        result = self._runner(
            [
                "ffmpeg",
                "-hide_banner",
                "-i",
                context.video_path,
                "-filter:v",
                "select='gt(scene,0.35)',showinfo",
                "-f",
                "null",
                "-",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=1800,
        )
        return MultimodalProviderOutput(
            observations=parse_scene_showinfo(
                result.stderr,
                duration_ms=context.duration_ms,
                frame_rate=context.frame_rate,
            ),
            capability_states={"scene_segmentation": "available"},
        )


_ACTION_TERMS = (
    "確認",
    "檢查",
    "按下",
    "開啟",
    "關閉",
    "設定",
    "調整",
    "更換",
    "解除",
    "清潔",
    "停機",
    "啟動",
    "復歸",
    "掃描",
    "計數",
    "移除",
)
_STATE_TERMS = (
    "歸零",
    "運轉",
    "停止",
    "已開啟",
    "已關閉",
    "正常",
    "異常",
    "完成",
    "就緒",
)
_MEASUREMENT_RE = re.compile(
    r"(?P<name>壓力|溫度|速度|轉速|電流|電壓|濃度|張力)?\s*"
    r"(?P<value>-?\d+(?:\.\d+)?)\s*(?P<unit>bar|kpa|mpa|°?c|rpm|a|v|%|mm|cm)(?!\w)",
    re.IGNORECASE,
)


class EvidenceRuleTimelineProvider:
    """Conservative, labelled candidates from exact transcript/OCR evidence."""

    provider_key = "core.evidence_rules"
    provider_version = "1.0"
    capability_keys = (
        "speaker_diarization",
        "action_event",
        "equipment_state",
        "temporal_alignment",
    )
    execution_boundary = "local_deterministic_rules"

    @staticmethod
    def _observation(
        *,
        kind: str,
        label: str,
        text: str,
        start_ms: int,
        end_ms: int,
        confidence: float | None,
        speaker: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> TimelineObservation:
        return TimelineObservation(
            kind=kind,
            start_ms=start_ms,
            end_ms=max(start_ms + 1, end_ms),
            label=label,
            content=text,
            confidence=confidence,
            provider="core.evidence_rules",
            provider_version="1.0",
            speaker=speaker,
            attributes=attributes or {},
        )

    def analyze(self, context: MultimodalAnalysisContext) -> MultimodalProviderOutput:
        rows: list[TimelineObservation] = []
        has_speaker = False
        for segment in context.transcript_segments:
            text = str(segment.text or "").strip()
            if not text:
                continue
            if segment.speaker:
                has_speaker = True
                rows.append(
                    self._observation(
                        kind="speaker_turn",
                        label="speaker_turn",
                        text=text,
                        start_ms=segment.start_ms,
                        end_ms=segment.end_ms,
                        confidence=segment.confidence,
                        speaker=segment.speaker,
                        attributes={"speaker_source": "upstream_asr_or_diarization"},
                    )
                )
            if any(term in text for term in _ACTION_TERMS):
                rows.append(
                    self._observation(
                        kind="action_event",
                        label="spoken_action_candidate",
                        text=text,
                        start_ms=segment.start_ms,
                        end_ms=segment.end_ms,
                        confidence=segment.confidence,
                        speaker=segment.speaker,
                        attributes={"detection_method": "explicit_action_term"},
                    )
                )
            matches = list(_MEASUREMENT_RE.finditer(text))
            if matches or any(term in text for term in _STATE_TERMS):
                rows.append(
                    self._observation(
                        kind="equipment_state",
                        label="spoken_equipment_state_candidate",
                        text=text,
                        start_ms=segment.start_ms,
                        end_ms=segment.end_ms,
                        confidence=segment.confidence,
                        speaker=segment.speaker,
                        attributes={
                            "detection_method": "explicit_state_or_measurement",
                            "measurements": [match.groupdict() for match in matches],
                        },
                    )
                )

        for frame in context.keyframes:
            text = str(frame.ocr_text or "").strip()
            if not text:
                continue
            matches = list(_MEASUREMENT_RE.finditer(text))
            if matches or any(term in text for term in _STATE_TERMS):
                rows.append(
                    self._observation(
                        kind="equipment_state",
                        label="visual_equipment_state_candidate",
                        text=text,
                        start_ms=frame.timestamp_ms,
                        end_ms=frame.timestamp_ms + 1,
                        confidence=frame.ocr_confidence,
                        attributes={
                            "detection_method": "ocr_state_or_measurement",
                            "frame_index": frame.frame_index,
                            "measurements": [match.groupdict() for match in matches],
                        },
                    )
                )
        return MultimodalProviderOutput(
            observations=rows,
            capability_states={
                "speaker_diarization": "available_upstream"
                if has_speaker
                else "unavailable",
                "action_event": "candidate_rules",
                "equipment_state": "candidate_rules",
                "temporal_alignment": "available",
            },
        )


class AudioSignalOutlierProvider:
    """Find acoustic outliers without claiming a machine-fault diagnosis."""

    provider_key = "core.audio_signal_outlier"
    provider_version = "1.0"
    capability_keys = ("audio_anomaly",)
    execution_boundary = "local_ffmpeg_signal_statistics"

    def __init__(self, runner: Any | None = None) -> None:
        self._runner = runner or subprocess.run

    def analyze(self, context: MultimodalAnalysisContext) -> MultimodalProviderOutput:
        if not context.has_audio:
            return MultimodalProviderOutput(
                capability_states={"audio_anomaly": "unavailable_no_audio"}
            )
        sample_rate = 8000
        result = self._runner(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                context.video_path,
                "-vn",
                "-ac",
                "1",
                "-ar",
                str(sample_rate),
                "-f",
                "s16le",
                "pipe:1",
            ],
            check=True,
            capture_output=True,
            timeout=1800,
        )
        samples = array("h")
        samples.frombytes(bytes(result.stdout or b""))
        if sys.byteorder != "little":
            samples.byteswap()
        rms_windows: list[float] = []
        for offset in range(0, len(samples), sample_rate):
            window = samples[offset : offset + sample_rate]
            if not window:
                continue
            rms_windows.append(
                (sum(float(value) ** 2 for value in window) / len(window)) ** 0.5
            )
        if len(rms_windows) < 3:
            return MultimodalProviderOutput(
                capability_states={"audio_anomaly": "insufficient_signal"}
            )
        baseline = median(rms_windows)
        deviation = median([abs(value - baseline) for value in rms_windows])
        threshold = baseline + max(3 * deviation, baseline, 500.0)
        observations = []
        for index, rms in enumerate(rms_windows):
            if rms <= threshold:
                continue
            start_ms = index * 1000
            if start_ms >= context.duration_ms:
                continue
            observations.append(
                TimelineObservation(
                    kind="audio_event",
                    start_ms=start_ms,
                    end_ms=min(context.duration_ms, start_ms + 1000),
                    label="acoustic_signal_outlier",
                    content="聲學能量與影片基準顯著不同，需人員聽辨確認",
                    confidence=min(0.99, 0.5 + (rms - threshold) / max(rms, 1) / 2),
                    provider=self.provider_key,
                    provider_version=self.provider_version,
                    attributes={
                        "detection_method": "one_second_rms_median_outlier",
                        "rms": round(rms, 2),
                        "baseline_rms": round(baseline, 2),
                        "threshold_rms": round(threshold, 2),
                        "semantic_diagnosis": False,
                    },
                )
            )
        return MultimodalProviderOutput(
            observations=observations,
            capability_states={"audio_anomaly": "candidate_signal_outlier"},
        )


class MultimodalProviderRegistry:
    def __init__(
        self, providers: list[MultimodalUnderstandingProvider] | None = None
    ) -> None:
        self._providers = providers or [
            FfmpegSceneProvider(),
            EvidenceRuleTimelineProvider(),
            AudioSignalOutlierProvider(),
        ]
        identities: set[tuple[str, str]] = set()
        for provider in self._providers:
            identity = (provider.provider_key, provider.provider_version)
            if identity in identities:
                raise ValueError(f"duplicate multimodal provider: {identity}")
            identities.add(identity)

    def analyze(
        self, context: MultimodalAnalysisContext
    ) -> MultimodalUnderstandingResult:
        result = MultimodalUnderstandingResult(
            capability_states={key: "unavailable" for key in _CAPABILITIES}
        )
        for provider in self._providers:
            try:
                output = provider.analyze(context)
                result.observations.extend(output.observations)
                for capability, state in output.capability_states.items():
                    current = result.capability_states.get(capability, "unavailable")
                    rank = {
                        "unavailable": 0,
                        "failed": 1,
                        "candidate_rules": 2,
                        "candidate_signal_outlier": 2,
                        "available_upstream": 3,
                        "available": 4,
                    }
                    if rank.get(state, 0) >= rank.get(current, 0):
                        result.capability_states[capability] = state
            except Exception as exc:
                logger.exception(
                    "multimodal provider failed: %s", provider.provider_key
                )
                result.provider_failures.append(
                    {
                        "provider": provider.provider_key,
                        "capabilities": list(provider.capability_keys),
                        "error": str(exc)[:300],
                    }
                )
                for capability in provider.capability_keys:
                    if result.capability_states.get(capability) == "unavailable":
                        result.capability_states[capability] = "failed"
        result.observations.sort(key=lambda row: (row.start_ms, row.kind, row.label))
        return result


def analyze_multimodal_timeline(
    video_path: str,
    processing: VideoProcessingResult,
    *,
    registry: MultimodalProviderRegistry | None = None,
) -> MultimodalUnderstandingResult:
    context = MultimodalAnalysisContext(
        video_path=video_path,
        duration_ms=processing.probe.duration_ms,
        frame_rate=processing.probe.frame_rate,
        has_audio=processing.probe.has_audio,
        transcript_segments=tuple(processing.transcript_segments),
        keyframes=tuple(processing.keyframes),
    )
    if registry is None:
        from app.composition.multimodal import build_multimodal_provider_registry

        registry = build_multimodal_provider_registry()
    return registry.analyze(context)


_KIND_MAP = {
    "video_scene": "video_scene",
    "speaker_turn": "speaker_turn",
    "action_event": "action_event",
    "equipment_state": "equipment_state",
    "audio_event": "audio_event",
}


def project_multimodal_timeline(
    db: Session,
    revision: AssetRevision,
    understanding: MultimodalUnderstandingResult,
) -> dict[str, Any]:
    projected: list[DerivedArtifact] = []
    timeline_entries: list[dict[str, Any]] = []
    for observation in understanding.observations:
        artifact_kind = _KIND_MAP.get(observation.kind)
        if artifact_kind is None:
            continue
        artifact = _upsert_artifact(
            db,
            revision,
            artifact_kind=artifact_kind,
            content=observation.content,
            confidence=observation.confidence,
            quality_state="review_required",
            metadata={
                "label": observation.label,
                "start_ms": observation.start_ms,
                "end_ms": observation.end_ms,
                "speaker": observation.speaker,
                "frame_index": observation.frame_index,
                "source_provider": observation.provider,
                "source_provider_version": observation.provider_version,
                **observation.attributes,
            },
            provider=observation.provider,
            provider_version=observation.provider_version,
        )
        _ensure_video_evidence(
            db,
            revision,
            artifact,
            start_ms=observation.start_ms,
            end_ms=observation.end_ms,
            frame_index=observation.frame_index,
            speaker=observation.speaker,
        )
        projected.append(artifact)
        timeline_entries.append(
            {
                "artifact_id": str(artifact.id),
                "kind": artifact_kind,
                "start_ms": observation.start_ms,
                "end_ms": observation.end_ms,
            }
        )

    source_rows = (
        db.query(DerivedArtifact)
        .filter(
            DerivedArtifact.tenant_id == revision.tenant_id,
            DerivedArtifact.asset_revision_id == revision.id,
            DerivedArtifact.artifact_kind.in_(
                ("transcript_segment", "keyframe", "ocr_region")
            ),
        )
        .all()
    )
    from app.models.asset import EvidenceSpan

    for source in source_rows:
        spans = (
            db.query(EvidenceSpan)
            .filter(
                EvidenceSpan.tenant_id == revision.tenant_id,
                EvidenceSpan.artifact_id == source.id,
                EvidenceSpan.asset_revision_id == revision.id,
            )
            .all()
        )
        timeline_entries.extend(
            {
                "artifact_id": str(source.id),
                "kind": source.artifact_kind,
                "start_ms": int(span.start_ms or 0),
                "end_ms": int(span.end_ms or (span.start_ms or 0) + 1),
            }
            for span in spans
        )

    unique_entries = {
        (entry["artifact_id"], entry["start_ms"], entry["end_ms"]): entry
        for entry in timeline_entries
    }
    timeline_entries = sorted(
        unique_entries.values(), key=lambda entry: (entry["start_ms"], entry["kind"])
    )
    scene_ranges = [
        (entry["start_ms"], entry["end_ms"])
        for entry in timeline_entries
        if entry["kind"] == "video_scene"
    ]
    if not scene_ranges:
        duration_ms = max(1, int(revision.duration_ms or 1))
        scene_ranges = [
            (start, min(duration_ms, start + 30_000))
            for start in range(0, duration_ms, 30_000)
        ]
    aligned_windows = [
        {
            "start_ms": start,
            "end_ms": end,
            "entries": [
                entry
                for entry in timeline_entries
                if entry["start_ms"] < end and entry["end_ms"] > start
            ],
        }
        for start, end in scene_ranges
    ]

    timeline = _upsert_artifact(
        db,
        revision,
        artifact_kind="timeline_alignment",
        content=json.dumps(
            {
                "schema_version": "1.0",
                "capability_states": understanding.capability_states,
                "provider_failures": understanding.provider_failures,
                "entries": timeline_entries,
                "windows": aligned_windows,
            },
            ensure_ascii=False,
        ),
        quality_state="review_required",
        metadata={"entry_count": len(timeline_entries)},
    )
    _ensure_video_evidence(
        db,
        revision,
        timeline,
        start_ms=0,
        end_ms=max(1, int(revision.duration_ms or 1)),
    )
    public_provider_failures = [
        {
            "provider": str(failure.get("provider") or "unknown"),
            "capabilities": list(failure.get("capabilities") or []),
        }
        for failure in understanding.provider_failures
    ]
    return {
        "timeline_artifact_id": str(timeline.id),
        "observation_count": len(projected),
        "capability_states": understanding.capability_states,
        # Technical exception text remains in the governed timeline artifact;
        # job readiness is user-visible and therefore only exposes identity.
        "provider_failures": public_provider_failures,
    }
