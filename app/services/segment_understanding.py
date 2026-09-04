"""Evidence-complete segment understanding and hierarchical summaries (AV4)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.asset import AssetRevision, DerivedArtifact, EvidenceSpan
from app.platform.multimodal import (
    MultimodalSegmentCandidate,
    MultimodalSegmentInput,
    SegmentEvidence,
    SegmentUnderstandingProvider,
)
from app.services.video_processing import _ensure_video_evidence, _upsert_artifact


SUPPORTED_CANDIDATES = {
    "action",
    "state",
    "measurement",
    "condition",
    "exception",
    "risk",
    "prohibition",
    "contradiction",
}


class EvidenceCompletenessError(ValueError):
    pass


@dataclass(frozen=True)
class SegmentResult:
    segment: MultimodalSegmentInput
    candidates: tuple[MultimodalSegmentCandidate, ...]
    provider_state: str


def validate_candidates(
    segment: MultimodalSegmentInput, candidates: list[MultimodalSegmentCandidate]
) -> list[MultimodalSegmentCandidate]:
    available = {row.artifact_id for row in segment.evidence}
    valid: list[MultimodalSegmentCandidate] = []
    for candidate in candidates:
        if candidate.candidate_type not in SUPPORTED_CANDIDATES:
            raise EvidenceCompletenessError("unsupported segment candidate type")
        if not candidate.statement.strip() or not candidate.evidence_artifact_ids:
            raise EvidenceCompletenessError(
                "segment candidate lacks statement or evidence"
            )
        if not set(candidate.evidence_artifact_ids) <= available:
            raise EvidenceCompletenessError(
                "segment candidate references foreign evidence"
            )
        if (
            candidate.risk_level in {"high", "critical"}
            and candidate.confidence is None
        ):
            # Unknown confidence is accepted only as review-required; never publishable.
            candidate = replace(
                candidate,
                attributes={**candidate.attributes, "requires_human_review": True},
            )
        valid.append(candidate)
    return valid


class ConservativeSegmentProvider:
    """Local fallback which only restates explicit evidence, never infers actions."""

    provider_key = "core.segment_evidence"
    provider_version = "1.0"
    execution_boundary = "local_deterministic_rules"

    def understand(
        self, segment: MultimodalSegmentInput
    ) -> list[MultimodalSegmentCandidate]:
        candidates: list[MultimodalSegmentCandidate] = []
        for evidence in segment.evidence:
            candidate_type = {
                "action_event": "action",
                "equipment_state": "state",
                "audio_event": "risk",
            }.get(evidence.kind)
            if candidate_type:
                candidates.append(
                    MultimodalSegmentCandidate(
                        candidate_type=candidate_type,
                        statement=evidence.content,
                        evidence_artifact_ids=(evidence.artifact_id,),
                        risk_level="high" if candidate_type == "risk" else "normal",
                        confidence=None,
                        attributes={"inference": False, "review_required": True},
                    )
                )
        # Explicit ASR/OCR numeric disagreement is useful, but remains a candidate.
        transcript = [
            row for row in segment.evidence if row.kind == "transcript_segment"
        ]
        visual = [
            row for row in segment.evidence if row.kind in {"ocr_region", "ocr_track"}
        ]
        number_re = re.compile(r"-?\d+(?:\.\d+)?\s*(?:mpa|kpa|bar|°?c|rpm|%|mm)", re.I)
        spoken_values = {
            value.lower()
            for row in transcript
            for value in number_re.findall(row.content)
        }
        visual_values = {
            value.lower() for row in visual for value in number_re.findall(row.content)
        }
        if spoken_values and visual_values and spoken_values.isdisjoint(visual_values):
            refs = tuple(row.artifact_id for row in [*transcript, *visual])
            candidates.append(
                MultimodalSegmentCandidate(
                    candidate_type="contradiction",
                    statement=f"語音數值 {sorted(spoken_values)} 與畫面數值 {sorted(visual_values)} 不一致",
                    evidence_artifact_ids=refs,
                    risk_level="high",
                    confidence=1.0,
                    attributes={"requires_human_review": True},
                )
            )
        return candidates


def build_segments(
    evidence: list[SegmentEvidence],
    *,
    duration_ms: int,
    scene_ranges: list[tuple[int, int]] | None = None,
) -> list[MultimodalSegmentInput]:
    ranges = scene_ranges or [
        (start, min(duration_ms, start + 30_000))
        for start in range(0, max(duration_ms, 1), 30_000)
    ]
    return [
        MultimodalSegmentInput(
            segment_id=f"segment-{index:05d}",
            start_ms=start,
            end_ms=end,
            evidence=tuple(
                row for row in evidence if row.start_ms < end and row.end_ms > start
            ),
        )
        for index, (start, end) in enumerate(ranges)
        if end > start
    ]


def understand_segments(
    segments: list[MultimodalSegmentInput],
    provider: SegmentUnderstandingProvider | None = None,
) -> list[SegmentResult]:
    provider = provider or ConservativeSegmentProvider()
    results: list[SegmentResult] = []
    for segment in segments:
        try:
            candidates = validate_candidates(segment, provider.understand(segment))
            state = "available" if candidates else "completed_no_candidates"
        except Exception:
            candidates = []
            state = "degraded_provider_failure"
        results.append(SegmentResult(segment, tuple(candidates), state))
    return results


def project_segment_understanding(
    db: Session,
    revision: AssetRevision,
    *,
    provider: SegmentUnderstandingProvider | None = None,
    run_id: UUID | None = None,
) -> dict[str, Any]:
    source_artifacts = (
        db.query(DerivedArtifact)
        .filter(
            DerivedArtifact.tenant_id == revision.tenant_id,
            DerivedArtifact.asset_revision_id == revision.id,
            DerivedArtifact.artifact_kind.in_(
                (
                    "transcript_segment",
                    "ocr_region",
                    "ocr_track",
                    "action_event",
                    "equipment_state",
                    "audio_event",
                    "video_scene",
                )
            ),
        )
        .all()
    )
    source_ids = [row.id for row in source_artifacts]
    spans = (
        db.query(EvidenceSpan)
        .filter(
            EvidenceSpan.tenant_id == revision.tenant_id,
            EvidenceSpan.asset_revision_id == revision.id,
            EvidenceSpan.artifact_id.in_(source_ids),
        )
        .all()
        if source_ids
        else []
    )
    by_artifact = {row.id: row for row in source_artifacts}
    evidence = [
        SegmentEvidence(
            artifact_id=str(span.artifact_id),
            kind=by_artifact[span.artifact_id].artifact_kind,
            start_ms=int(span.start_ms or 0),
            end_ms=int(span.end_ms or (span.start_ms or 0) + 1),
            content=str(by_artifact[span.artifact_id].content or ""),
        )
        for span in spans
        if span.artifact_id in by_artifact
    ]
    scenes = [
        (row.start_ms, row.end_ms) for row in evidence if row.kind == "video_scene"
    ]
    results = understand_segments(
        build_segments(
            evidence,
            duration_ms=max(1, int(revision.duration_ms or 1)),
            scene_ranges=scenes or None,
        ),
        provider,
    )
    artifact_ids: list[str] = []
    degraded = 0
    for result in results:
        if result.provider_state.startswith("degraded"):
            degraded += 1
        payload = {
            "schema_version": "2.0",
            "segment_id": result.segment.segment_id,
            "start_ms": result.segment.start_ms,
            "end_ms": result.segment.end_ms,
            "provider_state": result.provider_state,
            "candidates": [candidate.__dict__ for candidate in result.candidates],
            "summary": "；".join(
                candidate.statement for candidate in result.candidates
            ),
            "evidence_artifact_ids": sorted(
                {
                    ref
                    for candidate in result.candidates
                    for ref in candidate.evidence_artifact_ids
                }
            ),
            "publishable": False,
        }
        artifact = _upsert_artifact(
            db,
            revision,
            artifact_kind="multimodal_segment_summary",
            content=json.dumps(payload, ensure_ascii=False, sort_keys=True),
            quality_state="review_required",
            metadata={
                "segment_id": result.segment.segment_id,
                "start_ms": result.segment.start_ms,
                "end_ms": result.segment.end_ms,
                "provider_state": result.provider_state,
            },
            provider=getattr(provider, "provider_key", "core.segment_evidence"),
            provider_version=getattr(provider, "provider_version", "1.0"),
        )
        _ensure_video_evidence(
            db,
            revision,
            artifact,
            start_ms=result.segment.start_ms,
            end_ms=result.segment.end_ms,
        )
        if run_id is not None:
            from app.services.media_analysis_runs import project_derivation_link

            for parent_id in sorted(
                {UUID(value) for value in payload["evidence_artifact_ids"]}, key=str
            ):
                project_derivation_link(
                    db,
                    tenant_id=revision.tenant_id,
                    run_id=run_id,
                    parent_artifact_id=parent_id,
                    child_artifact_id=artifact.id,
                    relation_kind="summarized_into",
                    metadata={"segment_id": result.segment.segment_id},
                )
        artifact_ids.append(str(artifact.id))
    return {
        "segment_summary_artifact_ids": artifact_ids,
        "segment_count": len(results),
        "segment_provider_degraded_count": degraded,
        "segment_candidates_publishable": False,
    }
