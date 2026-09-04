"""Provider-neutral contracts for evidence-grounded media understanding."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class TimelineObservation:
    """One bounded candidate on the source media timeline."""

    kind: str
    start_ms: int
    end_ms: int
    label: str
    content: str
    confidence: float | None
    provider: str
    provider_version: str
    frame_index: int | None = None
    speaker: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.start_ms < 0 or self.end_ms <= self.start_ms:
            raise ValueError("timeline observation requires a positive time range")
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("timeline confidence must be between zero and one")
        if not self.kind or not self.provider or not self.provider_version:
            raise ValueError("timeline observation identity is incomplete")


@dataclass(frozen=True)
class MultimodalAnalysisContext:
    video_path: str
    duration_ms: int
    frame_rate: float
    has_audio: bool
    transcript_segments: tuple[Any, ...]
    keyframes: tuple[Any, ...]


@dataclass
class MultimodalProviderOutput:
    observations: list[TimelineObservation] = field(default_factory=list)
    capability_states: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class MultimodalUnderstandingProvider(Protocol):
    provider_key: str
    provider_version: str
    capability_keys: tuple[str, ...]
    execution_boundary: str

    def analyze(
        self, context: MultimodalAnalysisContext
    ) -> MultimodalProviderOutput: ...


@dataclass(frozen=True)
class SegmentEvidence:
    artifact_id: str
    kind: str
    start_ms: int
    end_ms: int
    content: str


@dataclass(frozen=True)
class MultimodalSegmentInput:
    segment_id: str
    start_ms: int
    end_ms: int
    evidence: tuple[SegmentEvidence, ...]
    entity_context: tuple[str, ...] = ()


@dataclass(frozen=True)
class MultimodalSegmentCandidate:
    candidate_type: str
    statement: str
    evidence_artifact_ids: tuple[str, ...]
    risk_level: str = "normal"
    confidence: float | None = None
    attributes: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class SegmentUnderstandingProvider(Protocol):
    provider_key: str
    provider_version: str
    execution_boundary: str

    def understand(self, segment: MultimodalSegmentInput) -> list[MultimodalSegmentCandidate]: ...
