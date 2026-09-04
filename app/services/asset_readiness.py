"""Canonical user-facing readiness for source-neutral knowledge assets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
from uuid import UUID

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.models.asset import AssetRevision, DerivedArtifact, SourceAsset
from app.config import settings
from app.models.document import Document, DocumentChunk
from app.models.ingestion import IngestionJob
from app.models.knowledge_engine import DocumentProfile
from app.models.knowledge_unit import (
    KnowledgeUnitRecord,
    KnowledgeUnitRelease,
    KnowledgeUnitReleaseMembership,
    KnowledgeUnitRevision,
)
from app.services.document_readiness import load_document_answer_states

_NON_ACTIONABLE_REVIEW_KINDS = {
    "speaker_turn",
    "video_scene",
    "timeline_alignment",
    "sop_conflict_report",
}


@dataclass(frozen=True)
class AssetReadinessState:
    answer_ready: bool
    lifecycle_status: str
    pending_review_count: int
    readiness_reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "answer_ready": self.answer_ready,
            "lifecycle_status": self.lifecycle_status,
            "pending_review_count": self.pending_review_count,
            "readiness_reasons": list(self.readiness_reasons),
        }


def is_asset_answer_ready(
    *, document_ready: bool, released_unit: bool, job_status: str | None
) -> bool:
    """Do not serve a first draft while its current source still needs review.

    A previously released immutable unit remains usable while a newer source
    revision is being reviewed.  A first-time shadow document does not.
    """
    if released_unit:
        return True
    return document_ready and job_status != "review_required"


def derive_asset_lifecycle(
    *,
    answer_ready: bool,
    job_status: str | None,
    asset_status: str | None,
    pending_review_count: int,
) -> tuple[str, tuple[str, ...]]:
    """Derive one mutually exclusive primary state from authoritative facts."""

    if job_status == "failed" or asset_status == "failed":
        return "needs_attention", ("processing_failed",)
    if job_status in {"queued", "running"}:
        return "processing", ("processing_not_completed",)
    if answer_ready:
        return "answer_ready", ()
    if job_status == "review_required" or pending_review_count > 0:
        return "awaiting_review", ("human_review_required",)
    if job_status == "ready":
        return "needs_attention", ("no_answer_ready_knowledge",)
    return "received", ("not_processed",)


def load_asset_readiness_states(
    db: Session,
    *,
    tenant_id: UUID,
    assets: Iterable[SourceAsset],
    jobs_by_revision: dict[UUID, IngestionJob] | None = None,
) -> dict[UUID, AssetReadinessState]:
    assets_by_id = {asset.id: asset for asset in assets}
    if not assets_by_id:
        return {}
    asset_ids = list(assets_by_id)

    revisions = db.query(AssetRevision).filter(
        AssetRevision.tenant_id == tenant_id,
        AssetRevision.asset_id.in_(asset_ids),
    ).all()
    current_revision_by_asset = {
        revision.asset_id: revision
        for revision in revisions
        if revision.revision == assets_by_id[revision.asset_id].current_revision
    }

    if jobs_by_revision is None:
        jobs_by_revision = {}
        revision_ids = [revision.id for revision in current_revision_by_asset.values()]
        if revision_ids:
            for job in db.query(IngestionJob).filter(
                IngestionJob.tenant_id == tenant_id,
                IngestionJob.asset_revision_id.in_(revision_ids),
            ).order_by(IngestionJob.created_at.desc()):
                jobs_by_revision.setdefault(job.asset_revision_id, job)

    documents = db.query(Document).filter(
        Document.tenant_id == tenant_id,
        Document.source_asset_id.in_(asset_ids),
        Document.tombstoned_at.is_(None),
    ).all()
    document_states = load_document_answer_states(
        db, tenant_id=tenant_id, documents=documents
    )
    document_ready_assets = {
        document.source_asset_id
        for document in documents
        if document.source_asset_id is not None
        and document_states.get(document.id) is not None
        and document_states[document.id].answer_ready
    }
    # The serving label must describe what Ask can use in the currently
    # configured read mode.  During authority shadow migration the live
    # retriever still serves the completed current document revision, while
    # enforce mode requires immutable active-release membership above.
    if settings.KNOWLEDGE_UNIT_READ_MODE == "shadow" and documents:
        document_ids = [document.id for document in documents]
        ready_profile_keys = {
            (document_id, int(revision))
            for document_id, revision in db.query(
                DocumentProfile.document_id,
                DocumentProfile.document_revision,
            ).filter(
                DocumentProfile.tenant_id == tenant_id,
                DocumentProfile.document_id.in_(document_ids),
                DocumentProfile.answer_ready.is_(True),
            )
        }
        chunk_keys = {
            (document_id, int(revision))
            for document_id, revision in db.query(
                DocumentChunk.document_id,
                DocumentChunk.document_revision,
            ).filter(
                DocumentChunk.tenant_id == tenant_id,
                DocumentChunk.document_id.in_(document_ids),
            ).distinct()
        }
        document_ready_assets.update(
            document.source_asset_id
            for document in documents
            if document.source_asset_id is not None
            and document.status == "completed"
            and (
                document.id,
                int(document.version or 1),
            ) in ready_profile_keys
            and (
                document.id,
                int(document.version or 1),
            ) in chunk_keys
        )

    released_asset_ids = {
        row[0]
        for row in db.query(KnowledgeUnitRecord.source_asset_id)
        .join(
            KnowledgeUnitRevision,
            and_(
                KnowledgeUnitRevision.tenant_id == KnowledgeUnitRecord.tenant_id,
                KnowledgeUnitRevision.unit_id == KnowledgeUnitRecord.id,
                KnowledgeUnitRevision.revision == KnowledgeUnitRecord.current_revision,
            ),
        )
        .join(
            KnowledgeUnitReleaseMembership,
            and_(
                KnowledgeUnitReleaseMembership.tenant_id
                == KnowledgeUnitRevision.tenant_id,
                KnowledgeUnitReleaseMembership.unit_revision_id
                == KnowledgeUnitRevision.id,
                KnowledgeUnitReleaseMembership.status == "active",
            ),
        )
        .join(
            KnowledgeUnitRelease,
            and_(
                KnowledgeUnitRelease.tenant_id
                == KnowledgeUnitReleaseMembership.tenant_id,
                KnowledgeUnitRelease.id
                == KnowledgeUnitReleaseMembership.release_id,
                KnowledgeUnitRelease.status == "active",
            ),
        )
        .filter(
            KnowledgeUnitRecord.tenant_id == tenant_id,
            KnowledgeUnitRecord.source_asset_id.in_(asset_ids),
            KnowledgeUnitRecord.status == "active",
            KnowledgeUnitRecord.tombstoned_at.is_(None),
            KnowledgeUnitRevision.quality_state == "ready",
        )
        .distinct()
    }

    current_revision_ids = [
        revision.id for revision in current_revision_by_asset.values()
    ]
    review_counts = {
        asset_id: int(count)
        for asset_id, count in db.query(AssetRevision.asset_id, func.count(DerivedArtifact.id))
        .join(
            DerivedArtifact,
            and_(
                DerivedArtifact.tenant_id == AssetRevision.tenant_id,
                DerivedArtifact.asset_revision_id == AssetRevision.id,
            ),
        )
        .filter(
            AssetRevision.tenant_id == tenant_id,
            AssetRevision.asset_id.in_(asset_ids),
            DerivedArtifact.asset_revision_id.in_(current_revision_ids),
            DerivedArtifact.quality_state == "review_required",
            ~DerivedArtifact.artifact_kind.in_(_NON_ACTIONABLE_REVIEW_KINDS),
        )
        .group_by(AssetRevision.asset_id)
    }

    result: dict[UUID, AssetReadinessState] = {}
    for asset_id, asset in assets_by_id.items():
        current_revision = current_revision_by_asset.get(asset_id)
        job = jobs_by_revision.get(current_revision.id) if current_revision else None
        answer_ready = is_asset_answer_ready(
            document_ready=asset_id in document_ready_assets,
            released_unit=asset_id in released_asset_ids,
            job_status=job.status if job else None,
        )
        pending_review_count = review_counts.get(asset_id, 0)
        lifecycle, reasons = derive_asset_lifecycle(
            answer_ready=answer_ready,
            job_status=job.status if job else None,
            asset_status=asset.status,
            pending_review_count=pending_review_count,
        )
        result[asset_id] = AssetReadinessState(
            answer_ready=answer_ready,
            lifecycle_status=lifecycle,
            pending_review_count=pending_review_count,
            readiness_reasons=reasons,
        )
    return result
