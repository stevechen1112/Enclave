#!/usr/bin/env python3
"""Backfill truthful capability outcomes for terminal legacy ingestion jobs."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone

from app.db.session import SessionLocal
from app.models.asset import AssetRevision, DerivedArtifact, SourceAsset
from app.models.ingestion import IngestionJob
from app.models.user import User


def _result(status: str, *, count: int = 0, reason: str | None = None) -> dict:
    return {
        "status": status,
        "reason_code": reason,
        "artifact_count": count,
        "provider": None,
        "details": {"source": "historical_artifact_backfill"},
    }


def infer_results(kind: str, requested: list[str], counts: Counter[str]) -> dict[str, dict]:
    transcript = counts["transcript_segment"]
    keyframes = counts["keyframe"]
    common = {"resumable_upload", "background_progress", "partial_readiness"}
    artifact_for = {
        "browser_proxy": "media_proxy", "keyframe": "keyframe", "ocr": "ocr_region",
        "procedure_candidate": "procedure_candidate", "scene_segment": "video_scene",
        "action_candidate": "action_event", "audio_event": "audio_event",
        "temporal_align": "timeline_alignment", "diarize": "speaker_turn",
    }
    results: dict[str, dict] = {}
    for capability in requested:
        if capability in common or capability == "probe_metadata":
            results[capability] = _result("available", count=1)
        elif capability == "transcribe":
            results[capability] = _result("available" if transcript else "not_applicable", count=transcript, reason=None if transcript else "no_speech_detected")
        elif capability == "timestamp":
            count = transcript + keyframes
            results[capability] = _result("available" if count else "not_applicable", count=count, reason=None if count else "no_timed_evidence")
        elif capability == "terminology_correction":
            results[capability] = _result("degraded", reason="terminology_correction_not_implemented")
        elif capability == "demux_audio":
            results[capability] = _result("available" if transcript else "not_applicable", count=transcript, reason=None if transcript else "no_audio_track")
        elif capability in {"extract_text", "layout"}:
            count = counts["extracted_text"]
            results[capability] = _result("available" if count else "failed", count=count, reason=None if count else "no_usable_text_extracted")
        elif capability in artifact_for:
            count = counts[artifact_for[capability]]
            results[capability] = _result("available" if count else "not_applicable", count=count, reason=None if count else "no_evidence_detected")
        else:
            results[capability] = _result("not_applicable", reason="no_evidence_detected")
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-email", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == args.tenant_email).first()
        if user is None:
            raise SystemExit("tenant user not found")
        rows = (
            db.query(SourceAsset, AssetRevision, IngestionJob)
            .join(AssetRevision, (AssetRevision.asset_id == SourceAsset.id) & (AssetRevision.revision == SourceAsset.current_revision))
            .join(IngestionJob, IngestionJob.asset_revision_id == AssetRevision.id)
            .filter(SourceAsset.tenant_id == user.tenant_id, SourceAsset.tombstoned_at.is_(None))
            .all()
        )
        changed = 0
        for asset, revision, job in rows:
            readiness = dict(job.readiness or {})
            if (
                readiness.get("capability_results")
                and not readiness.get("capability_results_backfilled_at")
            ) or job.status not in {"ready", "review_required"}:
                continue
            counts = Counter(
                kind for (kind,) in db.query(DerivedArtifact.artifact_kind)
                .filter(DerivedArtifact.tenant_id == user.tenant_id, DerivedArtifact.asset_revision_id == revision.id)
                .all()
            )
            readiness.update({
                "capability_results_schema": "input-capability-results.v1",
                "capability_results": infer_results(asset.asset_kind, list(job.requested_capabilities or []), counts),
                "capability_results_backfilled_at": datetime.now(timezone.utc).isoformat(),
            })
            job.readiness = readiness
            changed += 1
        if args.apply:
            db.commit()
        else:
            db.rollback()
        print(f"eligible_jobs={changed} applied={str(args.apply).lower()}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
