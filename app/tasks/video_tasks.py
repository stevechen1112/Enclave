"""Capability-routed worker for governed video ingestion."""

from __future__ import annotations

import logging
import os
import tempfile
import uuid
from pathlib import Path
from uuid import UUID

from app.celery_app import celery_app
from app.config import settings
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


@celery_app.task(
    name="tasks.process_video_asset",
    bind=True,
    max_retries=2,
    acks_late=True,
    soft_time_limit=1500,
    time_limit=1800,
)
def process_video_asset(self, tenant_id: str, revision_id: str, job_id: str):
    db = SessionLocal()
    tenant_uuid = UUID(tenant_id)
    from app.services.media_feature_flags import media_capability_enabled_for

    media_v2_enabled = media_capability_enabled_for(
        tenant_uuid, capability_enabled=True
    )
    adaptive_sampling_enabled = media_capability_enabled_for(
        tenant_uuid, capability_enabled=settings.VIDEO_ADAPTIVE_SAMPLING_V1
    )
    segment_understanding_enabled = media_capability_enabled_for(
        tenant_uuid, capability_enabled=settings.MULTIMODAL_SEGMENT_V1
    )
    entity_linking_enabled = media_capability_enabled_for(
        tenant_uuid, capability_enabled=settings.ENTITY_LINKING_V1
    )
    revision_uuid = UUID(revision_id)
    job_uuid = UUID(job_id)
    analysis_run = None
    try:
        from app.models.asset import AssetRevision, SourceAsset
        from app.models.ingestion import IngestionJob
        from app.services.ingestion_orchestrator import get_ingestion_orchestrator
        from app.services.rls import apply_rls_context

        apply_rls_context(db, tenant_uuid)
        revision = (
            db.query(AssetRevision)
            .filter(
                AssetRevision.tenant_id == tenant_uuid,
                AssetRevision.id == revision_uuid,
            )
            .one()
        )
        asset = (
            db.query(SourceAsset)
            .filter(
                SourceAsset.tenant_id == tenant_uuid,
                SourceAsset.id == revision.asset_id,
            )
            .one()
        )
        job = (
            db.query(IngestionJob)
            .filter(IngestionJob.tenant_id == tenant_uuid, IngestionJob.id == job_uuid)
            .one()
        )
        if job.status in {"review_required", "ready"}:
            return {"job_id": job_id, "status": job.status, "idempotent": True}

        orchestrator = get_ingestion_orchestrator()
        orchestrator.transition(db, job, to_status="running", phase="video_processing")
        revision.ingestion_status = "processing"
        db.commit()

        if media_v2_enabled:
            from app.services.media_analysis_runs import (
                get_or_create_analysis_run,
                transition_analysis_run,
            )

            analysis_run, _created = get_or_create_analysis_run(
                db,
                tenant_id=tenant_uuid,
                asset_revision_id=revision.id,
                pipeline_version="media-v2.1",
                profile=(
                    "video_adaptive"
                    if adaptive_sampling_enabled
                    else "video_compatibility"
                ),
                configuration={
                    "adaptive_sampling": adaptive_sampling_enabled,
                    "segment_understanding": segment_understanding_enabled,
                    "maximum_selected_frames": settings.MEDIA_V2_MAX_SELECTED_FRAMES,
                },
                provider_manifest={
                    "stt": settings.LONG_INTERVIEW_STT_MODEL,
                    "ocr": "tesseract",
                    "timeline": "core.multimodal",
                },
            )
            if analysis_run.status in {"queued", "failed", "degraded"}:
                transition_analysis_run(analysis_run, status="running")
            db.commit()

        from app.services.storage import build_storage_key, get_storage_backend
        from app.services.video_processing import (
            VideoPolicyError,
            probe_video,
            process_video_file,
            project_media_proxy,
            project_video_result,
        )

        backend = get_storage_backend()
        with tempfile.TemporaryDirectory(prefix="enclave-video-") as temp_dir:
            suffix = Path(
                str((revision.metadata_json or {}).get("filename") or ".mp4")
            ).suffix
            local_video = str(Path(temp_dir) / f"source{suffix or '.mp4'}")
            storage_key = str((revision.metadata_json or {}).get("storage_key") or "")
            if os.path.isfile(revision.content_uri):
                local_video = revision.content_uri
            elif storage_key:
                backend.get_to_file(storage_key, local_video)
            else:
                raise VideoPolicyError("video storage identity is unavailable")

            def progress(phase: str, readiness: dict) -> None:
                orchestrator.transition(
                    db,
                    job,
                    to_status="running",
                    phase=phase,
                    readiness={
                        "searchable": False,
                        "partial": phase.endswith("_partial"),
                        "requires_human_review": phase.endswith("_partial"),
                        **readiness,
                    },
                    details=readiness,
                )
                if analysis_run is not None:
                    from app.services.media_reliability import merge_checkpoint

                    analysis_run.checkpoint_json = merge_checkpoint(
                        dict(analysis_run.checkpoint_json or {}),
                        {"phase": phase, **readiness},
                    )
                db.commit()

            from app.services.media_productization import create_browser_video_proxy

            accepted_probe = probe_video(local_video)
            if entity_linking_enabled:
                from app.services.entity_knowledge_links import (
                    project_asset_entities_from_metadata,
                )

                project_asset_entities_from_metadata(
                    db,
                    tenant_id=tenant_uuid,
                    asset_revision_id=revision.id,
                    metadata={
                        **dict(asset.metadata_json or {}),
                        **dict(revision.metadata_json or {}),
                    },
                )
            if analysis_run is not None:
                from app.services.media_reliability import (
                    MediaCostRates,
                    enforce_media_cost_limit,
                    estimate_media_cost,
                )

                estimated_frames = min(
                    int(settings.MEDIA_V2_MAX_SELECTED_FRAMES),
                    max(
                        1,
                        round(
                            accepted_probe.duration_ms
                            / 1000
                            * float(settings.MEDIA_V2_SCAN_FPS_MIN)
                        ),
                    ),
                )
                estimate = estimate_media_cost(
                    duration_ms=accepted_probe.duration_ms,
                    selected_frames=estimated_frames,
                    precision_ratio=1.0,
                    rates=MediaCostRates(
                        settings.MEDIA_V2_STT_COST_PER_MINUTE,
                        settings.MEDIA_V2_PRECISION_STT_COST_PER_MINUTE,
                        settings.MEDIA_V2_VISION_COST_PER_FRAME,
                        settings.MEDIA_V2_OCR_COST_PER_FRAME,
                    ),
                )
                enforce_media_cost_limit(
                    estimate,
                    maximum_usd=float(settings.MEDIA_V2_MAX_COST_USD_PER_ASSET),
                )
                analysis_run.cost_metrics = {"estimate": estimate}
            expected_probe = dict((revision.metadata_json or {}).get("probe") or {})
            if expected_probe and (
                expected_probe.get("video_codec") != accepted_probe.video_codec
                or abs(
                    int(expected_probe.get("duration_ms") or 0)
                    - accepted_probe.duration_ms
                )
                > 1000
            ):
                raise VideoPolicyError("worker probe differs from accepted upload")

            if settings.MEDIA_PROXY_ENABLED:
                proxy_path = str(Path(temp_dir) / "review-proxy.mp4")
                create_browser_video_proxy(local_video, proxy_path)
                proxy_object_id = uuid.uuid5(
                    uuid.NAMESPACE_URL, f"enclave:{revision.id}:media-proxy:v1"
                )
                proxy_key = build_storage_key(tenant_uuid, proxy_object_id, ".mp4")
                proxy_size = os.path.getsize(proxy_path)
                proxy_uri = backend.put(proxy_key, proxy_path)
                project_media_proxy(
                    db,
                    revision,
                    artifact_uri=proxy_uri,
                    storage_key=proxy_key,
                    byte_size=proxy_size,
                )
                progress(
                    "proxy_ready",
                    {"preview_ready": True, "proxy_media_type": "video/mp4"},
                )

            result = process_video_file(
                local_video,
                temp_dir,
                probe=accepted_probe,
                progress=progress,
                adaptive_sampling_enabled=adaptive_sampling_enabled,
            )

            for keyframe in result.keyframes:
                object_id = uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"enclave:{revision.id}:keyframe:{keyframe.timestamp_ms}",
                )
                key = build_storage_key(tenant_uuid, object_id, ".jpg")
                keyframe.artifact_uri = backend.put(key, keyframe.path)
                keyframe.storage_key = key

            projection = project_video_result(
                db, revision, result, create_procedure_candidate=False
            )
            from app.services.video_understanding import (
                analyze_multimodal_timeline,
                project_multimodal_timeline,
            )

            understanding = analyze_multimodal_timeline(local_video, result)
            projection.update(project_multimodal_timeline(db, revision, understanding))
            if segment_understanding_enabled:
                from app.services.segment_understanding import (
                    project_segment_understanding,
                )

                projection.update(
                    project_segment_understanding(
                        db,
                        revision,
                        run_id=analysis_run.id if analysis_run is not None else None,
                    )
                )
            from app.services.video_governance import (
                project_governed_video_procedure,
            )

            projection.update(project_governed_video_procedure(db, revision))

            from app.services.input_capability_results import (
                readiness_with_capability_results,
                video_capability_results,
            )

            capability_results = video_capability_results(
                job.requested_capabilities or [],
                has_audio=accepted_probe.has_audio,
                audio_chunk_count=result.audio_chunk_count,
                transcript_count=int(projection.get("transcript_count") or 0),
                keyframe_count=int(projection.get("keyframe_count") or 0),
                ocr_count=int(projection.get("ocr_count") or 0),
                procedure_artifact_id=projection.get("procedure_artifact_id"),
                preview_ready=bool(settings.MEDIA_PROXY_ENABLED),
                capability_states=projection.get("capability_states") or {},
                provider_failures=projection.get("provider_failures") or [],
                stt_provider=result.stt_provider,
                stt_provider_version=result.stt_provider_version,
                stt_model=result.stt_model,
                stt_confidence_provider_supplied=(
                    result.stt_confidence_provider_supplied
                ),
                stt_calibration_version=result.stt_confidence_calibration_version,
            )

        if not projection.get("procedure_artifact_id"):
            revision.ingestion_status = "ready"
            asset.status = "active"
            orchestrator.transition(
                db,
                job,
                to_status="ready",
                phase="completed_no_knowledge",
                quality_state="rejected",
                readiness=readiness_with_capability_results(
                    {
                        "searchable": False,
                        "requires_human_review": False,
                        "reason": "no_evidence_backed_procedure_candidate",
                        **projection,
                    },
                    requested_capabilities=job.requested_capabilities or [],
                    observed=capability_results,
                ),
            )
            if analysis_run is not None:
                from app.services.media_analysis_runs import transition_analysis_run

                transition_analysis_run(
                    analysis_run,
                    status="completed",
                    checkpoint={
                        **dict(analysis_run.checkpoint_json or {}),
                        "phase": "completed_no_knowledge",
                    },
                )
            db.commit()
            return {"job_id": job_id, "status": job.status, **projection}

        revision.ingestion_status = "review_required"
        asset.status = "review_required"
        orchestrator.transition(
            db,
            job,
            to_status="review_required",
            phase="human_review",
            quality_state="review_required",
            readiness=readiness_with_capability_results(
                {
                    "searchable": False,
                    "requires_human_review": True,
                    **projection,
                },
                requested_capabilities=job.requested_capabilities or [],
                observed=capability_results,
            ),
        )
        if analysis_run is not None:
            from app.services.media_analysis_runs import transition_analysis_run

            transition_analysis_run(
                analysis_run,
                status="review_required",
                checkpoint={
                    **dict(analysis_run.checkpoint_json or {}),
                    "phase": "human_review",
                },
                quality_metrics={
                    "transcript_count": int(projection.get("transcript_count") or 0),
                    "keyframe_count": int(projection.get("keyframe_count") or 0),
                    "ocr_count": int(projection.get("ocr_count") or 0),
                    "segment_count": int(projection.get("segment_count") or 0),
                },
            )
        db.commit()
        return {"job_id": job_id, "status": job.status, **projection}
    except Exception as exc:
        db.rollback()
        logger.exception("video processing failed: revision=%s", revision_id)
        from app.services.ingestion_failures import classify_ingestion_failure

        failure = classify_ingestion_failure(exc)
        exhausted = (not failure.retryable) or self.request.retries >= self.max_retries
        try:
            from app.models.asset import AssetRevision, SourceAsset
            from app.models.ingestion import IngestionJob
            from app.services.ingestion_orchestrator import get_ingestion_orchestrator
            from app.services.rls import apply_rls_context

            apply_rls_context(db, tenant_uuid)
            job = (
                db.query(IngestionJob)
                .filter(
                    IngestionJob.tenant_id == tenant_uuid,
                    IngestionJob.id == job_uuid,
                )
                .first()
            )
            revision = (
                db.query(AssetRevision)
                .filter(
                    AssetRevision.tenant_id == tenant_uuid,
                    AssetRevision.id == revision_uuid,
                )
                .first()
            )
            if job is not None and job.status in {"queued", "running"}:
                if job.status == "queued":
                    get_ingestion_orchestrator().transition(
                        db, job, to_status="running", phase="video_processing"
                    )
                get_ingestion_orchestrator().fail(
                    db,
                    job,
                    code=failure.code,
                    message=failure.technical_message,
                    phase="video_processing",
                    category=failure.category,
                    retryable=failure.retryable,
                    user_message=failure.user_message,
                )
            if revision is not None:
                revision.ingestion_status = "failed" if exhausted else "pending"
                asset = (
                    db.query(SourceAsset)
                    .filter(
                        SourceAsset.tenant_id == tenant_uuid,
                        SourceAsset.id == revision.asset_id,
                    )
                    .first()
                )
                if asset is not None:
                    asset.status = "failed" if exhausted else "pending"
            if media_v2_enabled:
                from app.models.media_analysis import MediaAnalysisRun
                from app.services.media_analysis_runs import transition_analysis_run

                failed_run = (
                    db.query(MediaAnalysisRun)
                    .filter(
                        MediaAnalysisRun.tenant_id == tenant_uuid,
                        MediaAnalysisRun.asset_revision_id == revision_uuid,
                        MediaAnalysisRun.status == "running",
                    )
                    .order_by(MediaAnalysisRun.created_at.desc())
                    .first()
                )
                if failed_run is not None:
                    transition_analysis_run(
                        failed_run,
                        status="failed",
                        failure={"code": failure.code, "retryable": failure.retryable},
                    )
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("failed to persist video task failure state")
        if failure.retryable and self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))
        raise
    finally:
        db.close()
