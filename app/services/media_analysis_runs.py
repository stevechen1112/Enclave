"""Idempotent operational controls for media-v2 analysis runs."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.media_analysis import ArtifactDerivationLink, MediaAnalysisRun


def stable_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()


def get_or_create_analysis_run(
    db: Session,
    *,
    tenant_id: UUID,
    asset_revision_id: UUID,
    pipeline_version: str,
    profile: str,
    configuration: dict[str, Any],
    provider_manifest: dict[str, Any],
) -> tuple[MediaAnalysisRun, bool]:
    configuration_hash = stable_hash(configuration)
    run_key = stable_hash(
        [pipeline_version, profile, configuration_hash, provider_manifest]
    )[:64]
    existing = (
        db.query(MediaAnalysisRun)
        .filter(
            MediaAnalysisRun.tenant_id == tenant_id,
            MediaAnalysisRun.asset_revision_id == asset_revision_id,
            MediaAnalysisRun.run_key == run_key,
        )
        .first()
    )
    if existing is not None:
        return existing, False
    run = MediaAnalysisRun(
        tenant_id=tenant_id,
        asset_revision_id=asset_revision_id,
        run_key=run_key,
        pipeline_version=pipeline_version,
        profile=profile,
        provider_manifest=provider_manifest,
        configuration_json=configuration,
        configuration_hash=configuration_hash,
    )
    db.add(run)
    db.flush()
    return run, True


def transition_analysis_run(
    run: MediaAnalysisRun,
    *,
    status: str,
    checkpoint: dict[str, Any] | None = None,
    quality_metrics: dict[str, Any] | None = None,
    cost_metrics: dict[str, Any] | None = None,
    failure: dict[str, Any] | None = None,
) -> None:
    allowed = {
        "queued": {"running", "cancelled"},
        "running": {"review_required", "completed", "degraded", "failed", "cancelled"},
        "failed": {"running", "cancelled"},
        "review_required": {"completed", "cancelled"},
        "degraded": {"running", "completed", "cancelled"},
        "completed": set(),
        "cancelled": set(),
    }
    if status not in allowed.get(run.status, set()):
        raise ValueError(f"invalid media analysis transition: {run.status} -> {status}")
    now = datetime.now(timezone.utc)
    if status == "running" and run.started_at is None:
        run.started_at = now
    if status in {"completed", "degraded", "failed", "cancelled"}:
        run.completed_at = now
    run.status = status
    if checkpoint is not None:
        run.checkpoint_json = checkpoint
    if quality_metrics is not None:
        run.quality_metrics = quality_metrics
    if cost_metrics is not None:
        run.cost_metrics = cost_metrics
    if failure is not None:
        run.failure_json = failure


def project_derivation_link(
    db: Session,
    *,
    tenant_id: UUID,
    run_id: UUID,
    parent_artifact_id: UUID,
    child_artifact_id: UUID,
    relation_kind: str = "derived_from",
    metadata: dict[str, Any] | None = None,
) -> ArtifactDerivationLink:
    """Idempotently persist a real lineage edge, not only JSON metadata."""
    if parent_artifact_id == child_artifact_id:
        raise ValueError("artifact derivation cannot reference itself")
    row = (
        db.query(ArtifactDerivationLink)
        .filter(
            ArtifactDerivationLink.tenant_id == tenant_id,
            ArtifactDerivationLink.run_id == run_id,
            ArtifactDerivationLink.parent_artifact_id == parent_artifact_id,
            ArtifactDerivationLink.child_artifact_id == child_artifact_id,
            ArtifactDerivationLink.relation_kind == relation_kind,
        )
        .first()
    )
    if row is None:
        row = ArtifactDerivationLink(
            tenant_id=tenant_id,
            run_id=run_id,
            parent_artifact_id=parent_artifact_id,
            child_artifact_id=child_artifact_id,
            relation_kind=relation_kind,
            metadata_json=dict(metadata or {}),
        )
        db.add(row)
        db.flush()
    return row
