"""One tenant-scoped read model for audio/video review workspaces."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from app.models.asset import DerivedArtifact, EvidenceSpan
from app.models.media_analysis import AssetEntityLink, MediaAnalysisRun


def media_review_snapshot(
    db: Session, *, tenant_id: UUID, asset_revision_id: UUID
) -> dict[str, Any]:
    runs = (
        db.query(MediaAnalysisRun)
        .filter(
            MediaAnalysisRun.tenant_id == tenant_id,
            MediaAnalysisRun.asset_revision_id == asset_revision_id,
        )
        .order_by(MediaAnalysisRun.created_at.desc())
        .all()
    )
    kinds = (
        "audio_quality_profile",
        "transcript_raw",
        "transcript_correction",
        "ocr_track",
        "multimodal_segment_summary",
        "sop_conflict_report",
    )
    artifacts = (
        db.query(DerivedArtifact)
        .filter(
            DerivedArtifact.tenant_id == tenant_id,
            DerivedArtifact.asset_revision_id == asset_revision_id,
            DerivedArtifact.artifact_kind.in_(kinds),
        )
        .order_by(DerivedArtifact.created_at.asc())
        .all()
    )
    artifact_ids = [row.id for row in artifacts]
    spans = (
        db.query(EvidenceSpan)
        .filter(
            EvidenceSpan.tenant_id == tenant_id,
            EvidenceSpan.asset_revision_id == asset_revision_id,
            EvidenceSpan.artifact_id.in_(artifact_ids),
        )
        .all()
        if artifact_ids
        else []
    )
    by_artifact: dict[UUID, list[dict[str, Any]]] = {}
    for span in spans:
        by_artifact.setdefault(span.artifact_id, []).append(
            {
                "id": str(span.id),
                "kind": span.locator_kind,
                "start_ms": span.start_ms,
                "end_ms": span.end_ms,
                "speaker": span.speaker,
                "frame_index": span.frame_index,
            }
        )
    links = (
        db.query(AssetEntityLink)
        .filter(
            AssetEntityLink.tenant_id == tenant_id,
            AssetEntityLink.asset_revision_id == asset_revision_id,
            AssetEntityLink.status.in_(("candidate", "approved")),
        )
        .all()
    )

    def content(row: DerivedArtifact):
        try:
            return json.loads(row.content or "")
        except (json.JSONDecodeError, TypeError):
            return row.content

    return {
        "schema_version": "2.0",
        "runs": [
            {
                "id": str(run.id),
                "status": run.status,
                "profile": run.profile,
                "pipeline_version": run.pipeline_version,
                "provider_manifest": dict(run.provider_manifest or {}),
                "checkpoint": dict(run.checkpoint_json or {}),
                "quality_metrics": dict(run.quality_metrics or {}),
                "cost_metrics": dict(run.cost_metrics or {}),
                "failure": dict(run.failure_json or {}),
                "created_at": run.created_at,
                "completed_at": run.completed_at,
            }
            for run in runs
        ],
        "artifacts": [
            {
                "id": str(row.id),
                "kind": row.artifact_kind,
                "quality_state": row.quality_state,
                "confidence": row.confidence,
                "content": content(row),
                "metadata": dict(row.metadata_json or {}),
                "evidence": by_artifact.get(row.id, []),
            }
            for row in artifacts
        ],
        "entity_links": [
            {
                "id": str(link.id),
                "entity_id": str(link.entity_id),
                "link_kind": link.link_kind,
                "status": link.status,
                "confidence": link.confidence,
                "evidence": list(link.evidence_json or []),
            }
            for link in links
        ],
        "partial_use_allowed": any(row.quality_state == "ready" for row in artifacts),
    }


def safe_media_review_snapshot(
    db: Session, *, tenant_id: UUID, asset_revision_id: UUID
) -> dict[str, Any]:
    """Rolling-deploy fallback while the additive migration is not visible yet."""
    try:
        return media_review_snapshot(
            db, tenant_id=tenant_id, asset_revision_id=asset_revision_id
        )
    except SQLAlchemyError:
        db.rollback()
        return {
            "schema_version": "2.0",
            "runs": [],
            "artifacts": [],
            "entity_links": [],
            "partial_use_allowed": False,
            "unavailable_reason": "media_v2_schema_unavailable",
        }
