"""Tenant-scoped, bounded KnowledgeUnit authority backfill.

Examples:
  python scripts/backfill_knowledge_authority.py --tenant-id <uuid> --kind knowhow
  python scripts/backfill_knowledge_authority.py --tenant-id <uuid> --kind video --after-id <uuid>

The command never scans all tenants and prints a resumable checkpoint. Use
``--commit`` only after reviewing a dry run.
"""

# ruff: noqa: E402 -- the executable establishes the repository import root first

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from uuid import UUID

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from app.db.session import SessionLocal
from app.models.asset import (
    ArtifactReviewDecision,
    AssetRevision,
    DerivedArtifact,
    SourceAsset,
)
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase, KnowledgeBaseRevision
from app.models.mka import KnowhowCardModel
from app.services.knowledge_authority import (
    publish_approved_knowhow,
    publish_approved_video_procedure,
    publish_document_kb_revision,
)
from app.services.asset_projection import (
    AssetProjectionResult,
    publish_ready_document_extract,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument(
        "--kind",
        choices=("document", "source-extract", "knowhow", "video"),
        required=True,
    )
    parser.add_argument("--after-id", type=UUID)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--commit", action="store_true")
    return parser


def _after(query, column, after_id: UUID | None):
    return query.filter(column > after_id) if after_id else query


def main() -> int:
    args = _parser().parse_args()
    if not 1 <= args.limit <= 1000:
        raise SystemExit("--limit must be between 1 and 1000")
    db = SessionLocal()
    processed: list[str] = []
    try:
        if args.kind == "document":
            query = (
                db.query(KnowledgeBaseRevision)
                .join(KnowledgeBase)
                .filter(
                    KnowledgeBase.tenant_id == args.tenant_id,
                    KnowledgeBaseRevision.status == "active",
                )
                .order_by(KnowledgeBaseRevision.id)
            )
            for revision in _after(query, KnowledgeBaseRevision.id, args.after_id).limit(args.limit):
                publish_document_kb_revision(
                    db,
                    kb=revision.kb,
                    kb_revision=revision,
                    created_by=None,
                )
                processed.append(str(revision.id))
        elif args.kind == "source-extract":
            query = (
                db.query(DerivedArtifact, AssetRevision, SourceAsset, Document)
                .join(
                    AssetRevision,
                    (AssetRevision.tenant_id == DerivedArtifact.tenant_id)
                    & (AssetRevision.id == DerivedArtifact.asset_revision_id),
                )
                .join(
                    SourceAsset,
                    (SourceAsset.tenant_id == AssetRevision.tenant_id)
                    & (SourceAsset.id == AssetRevision.asset_id),
                )
                .join(
                    Document,
                    (Document.tenant_id == SourceAsset.tenant_id)
                    & (Document.source_asset_id == SourceAsset.id),
                )
                .filter(
                    DerivedArtifact.tenant_id == args.tenant_id,
                    DerivedArtifact.artifact_kind == "extracted_text",
                    DerivedArtifact.quality_state == "ready",
                    AssetRevision.revision == SourceAsset.current_revision,
                    AssetRevision.ingestion_status == "ready",
                    SourceAsset.tombstoned_at.is_(None),
                    Document.tombstoned_at.is_(None),
                )
                .order_by(DerivedArtifact.id)
            )
            query = _after(query, DerivedArtifact.id, args.after_id)
            for artifact, revision, asset, document in query.limit(args.limit):
                publish_ready_document_extract(
                    db,
                    document=document,
                    projection=AssetProjectionResult(
                        asset=asset,
                        revision=revision,
                        asset_created=False,
                        revision_created=False,
                    ),
                    artifact=artifact,
                )
                processed.append(str(artifact.id))
        elif args.kind == "knowhow":
            query = db.query(KnowhowCardModel).filter(
                KnowhowCardModel.tenant_id == args.tenant_id,
                KnowhowCardModel.status == "approved",
            ).order_by(KnowhowCardModel.id)
            for card in _after(query, KnowhowCardModel.id, args.after_id).limit(args.limit):
                if card.reviewer is None:
                    continue
                publish_approved_knowhow(db, card=card, reviewer_id=card.reviewer)
                processed.append(str(card.id))
        else:
            query = (
                db.query(ArtifactReviewDecision, DerivedArtifact, AssetRevision, SourceAsset)
                .join(DerivedArtifact, DerivedArtifact.id == ArtifactReviewDecision.artifact_id)
                .join(AssetRevision, AssetRevision.id == DerivedArtifact.asset_revision_id)
                .join(SourceAsset, SourceAsset.id == AssetRevision.asset_id)
                .filter(
                    ArtifactReviewDecision.tenant_id == args.tenant_id,
                    ArtifactReviewDecision.decision == "approved",
                    DerivedArtifact.artifact_kind == "procedure_candidate",
                )
                .order_by(ArtifactReviewDecision.id)
            )
            query = _after(query, ArtifactReviewDecision.id, args.after_id)
            for decision, artifact, revision, asset in query.limit(args.limit):
                payload = dict(decision.resolution_json or {}).get("published_procedure")
                if not isinstance(payload, dict) or decision.reviewer_id is None:
                    continue
                publish_approved_video_procedure(
                    db,
                    asset=asset,
                    asset_revision=revision,
                    artifact=artifact,
                    published_procedure=payload,
                    reviewer_id=decision.reviewer_id,
                    high_risk=bool(
                        dict(decision.resolution_json or {}).get(
                            "acknowledged_high_risk"
                        )
                    ),
                )
                processed.append(str(decision.id))
        if args.commit:
            db.commit()
        else:
            db.rollback()
        print(
            json.dumps(
                {
                    "tenant_id": str(args.tenant_id),
                    "kind": args.kind,
                    "committed": args.commit,
                    "processed": len(processed),
                    "next_checkpoint": processed[-1] if processed else None,
                },
                ensure_ascii=False,
            )
        )
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
