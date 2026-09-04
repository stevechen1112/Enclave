"""Resumable, bounded worker for long-form audio knowledge assets."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path
from uuid import UUID

from app.celery_app import celery_app
from app.config import settings
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


def _segment_digest(
    *, text: str, start_ms: int, end_ms: int, speaker: str | None
) -> str:
    payload = json.dumps(
        [text, start_ms, end_ms, speaker], ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@celery_app.task(
    name="tasks.process_audio_asset",
    bind=True,
    max_retries=2,
    acks_late=True,
    soft_time_limit=1500,
    time_limit=1800,
)
def process_audio_asset(self, tenant_id: str, revision_id: str, job_id: str):
    db = SessionLocal()
    tenant_uuid = UUID(tenant_id)
    from app.services.media_feature_flags import media_capability_enabled_for

    media_v2_enabled = media_capability_enabled_for(
        tenant_uuid, capability_enabled=True
    )
    audio_precision_enabled = media_capability_enabled_for(
        tenant_uuid, capability_enabled=settings.AUDIO_PRECISION_PASS_V1
    )
    entity_linking_enabled = media_capability_enabled_for(
        tenant_uuid, capability_enabled=settings.ENTITY_LINKING_V1
    )
    revision_uuid = UUID(revision_id)
    job_uuid = UUID(job_id)
    analysis_run = None
    try:
        from app.models.asset import (
            AssetRevision,
            DerivedArtifact,
            EvidenceSpan,
            SourceAsset,
        )
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
        if job.status in {"queued", "failed"}:
            orchestrator.transition(db, job, to_status="running", phase="audio_probe")
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
                    "audio_precision"
                    if audio_precision_enabled
                    else "audio_compatibility"
                ),
                configuration={
                    "precision_pass": audio_precision_enabled,
                    "chunk_target_seconds": 75,
                    "overlap_ms": 1500,
                },
                provider_manifest={
                    "pass_a": settings.LONG_INTERVIEW_STT_MODEL,
                    "pass_b": settings.VOICE_STT_MODEL,
                },
            )
            if analysis_run.status in {"queued", "failed", "degraded"}:
                transition_analysis_run(analysis_run, status="running")
            db.commit()
        from app.services.media_productization import (
            create_browser_audio_proxy,
            extract_audio_chunks,
            probe_audio,
            run_media_command,
        )
        from app.services.storage import build_storage_key, get_storage_backend
        from app.services.video_processing import project_media_proxy
        from app.services.voice_gateway import transcribe_long_interview_chunk
        from app.services.input_capability_results import (
            audio_capability_results,
            package_version,
            readiness_with_capability_results,
        )
        from app.services.input_quality import normalize_provider_confidence

        metadata = dict(revision.metadata_json or {})
        storage_key = str(metadata.get("storage_key") or "")
        if not storage_key and not os.path.isfile(revision.content_uri):
            raise RuntimeError("audio storage identity is unavailable")

        backend = get_storage_backend()
        # A retry may start after earlier chunks were committed. Terminal truth
        # must include those persisted segments, not only this attempt's output.
        artifact_ids: list[str] = [
            str(row.id)
            for row in db.query(DerivedArtifact.id)
            .filter(
                DerivedArtifact.tenant_id == tenant_uuid,
                DerivedArtifact.asset_revision_id == revision.id,
                DerivedArtifact.artifact_kind == "transcript_segment",
                DerivedArtifact.provider == "openai",
                DerivedArtifact.provider_version == "long_interview_stt.i5",
            )
            .all()
        ]
        with tempfile.TemporaryDirectory(prefix="enclave-audio-") as temp_dir:
            suffix = Path(str(metadata.get("filename") or ".webm")).suffix or ".webm"
            local_audio = str(Path(temp_dir) / f"source{suffix}")
            if os.path.isfile(revision.content_uri):
                local_audio = revision.content_uri
            else:
                backend.get_to_file(storage_key, local_audio)

            probe = probe_audio(local_audio)
            revision.duration_ms = probe.duration_ms
            if analysis_run is not None:
                from app.services.media_reliability import (
                    MediaCostRates,
                    enforce_media_cost_limit,
                    estimate_media_cost,
                )

                estimate = estimate_media_cost(
                    duration_ms=probe.duration_ms,
                    selected_frames=0,
                    precision_ratio=1.0 if audio_precision_enabled else 0.0,
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
            if settings.MEDIA_PROXY_ENABLED:
                from uuid import NAMESPACE_URL, uuid5

                proxy_path = str(Path(temp_dir) / "review-proxy.mp3")
                create_browser_audio_proxy(local_audio, proxy_path)
                proxy_object_id = uuid5(
                    NAMESPACE_URL, f"enclave:{revision.id}:audio-media-proxy:v1"
                )
                proxy_key = build_storage_key(tenant_uuid, proxy_object_id, ".mp3")
                proxy_size = os.path.getsize(proxy_path)
                proxy_uri = backend.put(proxy_key, proxy_path)
                project_media_proxy(
                    db,
                    revision,
                    artifact_uri=proxy_uri,
                    storage_key=proxy_key,
                    byte_size=proxy_size,
                    media_type="audio/mpeg",
                    browser_profile="mp3_mono_44k_96k",
                )
            orchestrator.transition(
                db,
                job,
                to_status="running",
                phase="audio_chunking",
                readiness={
                    "searchable": False,
                    "partial": False,
                    "requires_human_review": False,
                    "probe": probe.to_dict(),
                    "preview_ready": bool(settings.MEDIA_PROXY_ENABLED),
                },
            )
            db.commit()

            precision_enabled = audio_precision_enabled
            precision_plans = []
            audio_profile = None
            processing_source = local_audio
            if precision_enabled:
                from app.services.audio_precision import (
                    analyze_audio_quality,
                    build_adaptive_chunk_plan,
                    create_lossless_working_copy,
                    extract_lossless_chunks,
                )

                audio_profile = analyze_audio_quality(
                    local_audio,
                    duration_ms=probe.duration_ms,
                    sample_rate=probe.sample_rate,
                    channels=probe.channels,
                    runner=run_media_command,
                )
                processing_source = str(Path(temp_dir) / "working-16k-mono.wav")
                create_lossless_working_copy(
                    local_audio,
                    processing_source,
                    profile=audio_profile,
                    runner=run_media_command,
                )
                from uuid import NAMESPACE_URL, uuid5

                working_digest = hashlib.sha256(
                    Path(processing_source).read_bytes()
                ).hexdigest()
                working_artifact = (
                    db.query(DerivedArtifact)
                    .filter(
                        DerivedArtifact.tenant_id == tenant_uuid,
                        DerivedArtifact.asset_revision_id == revision.id,
                        DerivedArtifact.artifact_kind == "audio_working_copy",
                        DerivedArtifact.content_hash == working_digest,
                    )
                    .first()
                )
                if working_artifact is None:
                    working_object_id = uuid5(
                        NAMESPACE_URL,
                        f"enclave:{revision.id}:audio-working:{working_digest}",
                    )
                    working_key = build_storage_key(
                        tenant_uuid, working_object_id, ".wav"
                    )
                    working_uri = backend.put(working_key, processing_source)
                    working_artifact = DerivedArtifact(
                        tenant_id=tenant_uuid,
                        asset_revision_id=revision.id,
                        artifact_kind="audio_working_copy",
                        content_hash=working_digest,
                        provider="ffmpeg",
                        provider_version="pcm_s16le_16k_mono.v1",
                        quality_state="ready",
                        artifact_uri=working_uri,
                        metadata_json={
                            "storage_key": working_key,
                            "filter_profile": "adaptive_precision.v1",
                            "source_content_hash": revision.content_hash,
                        },
                        schema_version="2.0",
                    )
                    db.add(working_artifact)
                    db.flush()
                precision_plans = build_adaptive_chunk_plan(probe.duration_ms)
                chunks = extract_lossless_chunks(
                    processing_source,
                    temp_dir,
                    precision_plans,
                    runner=run_media_command,
                )
                profile_payload = json.dumps(
                    audio_profile.to_dict(), ensure_ascii=False, sort_keys=True
                )
                profile_digest = hashlib.sha256(profile_payload.encode()).hexdigest()
                if (
                    not db.query(DerivedArtifact.id)
                    .filter(
                        DerivedArtifact.tenant_id == tenant_uuid,
                        DerivedArtifact.asset_revision_id == revision.id,
                        DerivedArtifact.artifact_kind == "audio_quality_profile",
                        DerivedArtifact.content_hash == profile_digest,
                    )
                    .first()
                ):
                    db.add(
                        DerivedArtifact(
                            tenant_id=tenant_uuid,
                            asset_revision_id=revision.id,
                            artifact_kind="audio_quality_profile",
                            content_hash=profile_digest,
                            provider="core.audio",
                            provider_version="precision.v1",
                            quality_state=(
                                "review_required" if audio_profile.risks else "ready"
                            ),
                            content=profile_payload,
                            metadata_json={
                                "lossless_working_profile": "pcm_s16le_16k_mono"
                            },
                            schema_version="2.0",
                        )
                    )
                    db.flush()
            else:
                chunks = extract_audio_chunks(
                    processing_source,
                    temp_dir,
                    chunk_seconds=int(settings.AUDIO_CHUNK_SECONDS),
                )
            if not chunks:
                raise RuntimeError("audio chunking returned no decodable audio")

            previous_context = ""
            precision_degraded_chunks = 0
            for chunk_index, chunk_path in enumerate(chunks):
                with open(chunk_path, "rb") as stream:
                    result = transcribe_long_interview_chunk(
                        stream.read(),
                        filename=os.path.basename(chunk_path),
                        content_type=(
                            "audio/wav" if precision_enabled else "audio/mpeg"
                        ),
                    )
                segments = list(result.segments or [])
                if not segments and result.text.strip():
                    segments = [
                        {
                            "start": 0,
                            "end": max(float(result.duration_seconds or 0), 0.001),
                            "text": result.text,
                            "speaker": None,
                        }
                    ]
                offset_ms = (
                    precision_plans[chunk_index].start_ms
                    if precision_enabled
                    else chunk_index * int(settings.AUDIO_CHUNK_SECONDS) * 1000
                )
                if precision_enabled:
                    from app.services.audio_precision import extract_critical_tokens
                    from app.services.voice_gateway import transcribe_precision_chunk

                    glossary = [
                        str(value)
                        for value in (metadata.get("approved_glossary") or [])
                        if str(value).strip()
                    ]
                    raw_text = " ".join(
                        str(segment.get("text") or "").strip() for segment in segments
                    ).strip()
                    raw_digest = hashlib.sha256(
                        json.dumps([chunk_index, raw_text], ensure_ascii=False).encode()
                    ).hexdigest()
                    raw_artifact = (
                        db.query(DerivedArtifact)
                        .filter(
                            DerivedArtifact.tenant_id == tenant_uuid,
                            DerivedArtifact.asset_revision_id == revision.id,
                            DerivedArtifact.artifact_kind == "transcript_raw",
                            DerivedArtifact.content_hash == raw_digest,
                        )
                        .first()
                    )
                    if raw_artifact is None and raw_text:
                        raw_artifact = DerivedArtifact(
                            tenant_id=tenant_uuid,
                            asset_revision_id=revision.id,
                            artifact_kind="transcript_raw",
                            content_hash=raw_digest,
                            provider=result.provider or "openai",
                            provider_version=result.provider_version
                            or package_version("openai"),
                            quality_state="provisional",
                            content=raw_text,
                            metadata_json={
                                "chunk_index": chunk_index,
                                "start_ms": offset_ms,
                                "end_ms": precision_plans[chunk_index].end_ms,
                                "pass": "A_diarization",
                            },
                            schema_version="2.0",
                        )
                        db.add(raw_artifact)
                        db.flush()
                    from app.services.media_reliability import (
                        provider_circuit_breaker,
                    )

                    breaker = provider_circuit_breaker("openai:precision_stt")
                    try:
                        if not breaker.allow():
                            raise RuntimeError(
                                "precision transcription circuit breaker is open"
                            )
                        precision = transcribe_precision_chunk(
                            Path(chunk_path).read_bytes(),
                            filename=os.path.basename(chunk_path),
                            content_type="audio/wav",
                            glossary=glossary,
                            previous_context=previous_context,
                        )
                        breaker.record_success()
                    except Exception as precision_exc:
                        # Pass A is still useful and review-gated. A secondary
                        # provider failure must be visible but must not discard it.
                        logger.warning(
                            "audio precision pass degraded: revision=%s chunk=%s error=%s",
                            revision_id,
                            chunk_index,
                            precision_exc,
                        )
                        breaker.record_failure()
                        precision_degraded_chunks += 1
                        precision = None
                    if (
                        precision is not None
                        and precision.text
                        and precision.text.strip() != raw_text
                    ):
                        correction_payload = json.dumps(
                            {
                                "raw": raw_text,
                                "candidate": precision.text.strip(),
                                "critical_tokens": list(
                                    extract_critical_tokens(precision.text, glossary)
                                ),
                                "method": "contextual_asr_candidate",
                                "requires_human_review": True,
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        )
                        correction_digest = hashlib.sha256(
                            correction_payload.encode()
                        ).hexdigest()
                        correction_artifact = (
                            db.query(DerivedArtifact)
                            .filter(
                                DerivedArtifact.tenant_id == tenant_uuid,
                                DerivedArtifact.asset_revision_id == revision.id,
                                DerivedArtifact.artifact_kind
                                == "transcript_correction",
                                DerivedArtifact.content_hash == correction_digest,
                            )
                            .first()
                        )
                        if correction_artifact is None:
                            correction_artifact = DerivedArtifact(
                                tenant_id=tenant_uuid,
                                asset_revision_id=revision.id,
                                artifact_kind="transcript_correction",
                                content_hash=correction_digest,
                                provider=precision.provider or "openai",
                                provider_version=precision.provider_version
                                or package_version("openai"),
                                quality_state="review_required",
                                content=correction_payload,
                                metadata_json={
                                    "chunk_index": chunk_index,
                                    "start_ms": offset_ms,
                                    "end_ms": precision_plans[chunk_index].end_ms,
                                    "source_artifact_id": (
                                        str(raw_artifact.id) if raw_artifact else None
                                    ),
                                    "pass": "B_contextual",
                                },
                                schema_version="2.0",
                            )
                            db.add(correction_artifact)
                            db.flush()
                        if (
                            not db.query(EvidenceSpan.id)
                            .filter(
                                EvidenceSpan.tenant_id == tenant_uuid,
                                EvidenceSpan.artifact_id == correction_artifact.id,
                            )
                            .first()
                        ):
                            db.add(
                                EvidenceSpan(
                                    tenant_id=tenant_uuid,
                                    artifact_id=correction_artifact.id,
                                    asset_revision_id=revision.id,
                                    locator_kind="audio",
                                    start_ms=offset_ms,
                                    end_ms=precision_plans[chunk_index].end_ms,
                                )
                            )
                        if analysis_run is not None and raw_artifact is not None:
                            from app.services.media_analysis_runs import (
                                project_derivation_link,
                            )

                            project_derivation_link(
                                db,
                                tenant_id=tenant_uuid,
                                run_id=analysis_run.id,
                                parent_artifact_id=raw_artifact.id,
                                child_artifact_id=correction_artifact.id,
                                relation_kind="corrected_into",
                                metadata={"chunk_index": chunk_index},
                            )
                    previous_context = (previous_context + " " + raw_text)[-2000:]
                for segment in segments:
                    text = str(segment.get("text") or "").strip()
                    if not text:
                        continue
                    start_ms = min(
                        max(
                            0, offset_ms + int(float(segment.get("start") or 0) * 1000)
                        ),
                        max(0, probe.duration_ms - 1),
                    )
                    end_ms = min(
                        probe.duration_ms,
                        max(
                            start_ms + 1,
                            offset_ms + int(float(segment.get("end") or 0) * 1000),
                        ),
                    )
                    speaker = str(segment.get("speaker") or "").strip() or None
                    digest = _segment_digest(
                        text=text, start_ms=start_ms, end_ms=end_ms, speaker=speaker
                    )
                    artifact = (
                        db.query(DerivedArtifact)
                        .filter(
                            DerivedArtifact.tenant_id == tenant_uuid,
                            DerivedArtifact.asset_revision_id == revision.id,
                            DerivedArtifact.artifact_kind == "transcript_segment",
                            DerivedArtifact.provider == "openai",
                            DerivedArtifact.provider_version == "long_interview_stt.i5",
                            DerivedArtifact.content_hash == digest,
                        )
                        .first()
                    )
                    if artifact is None:
                        artifact = DerivedArtifact(
                            tenant_id=tenant_uuid,
                            asset_revision_id=revision.id,
                            artifact_kind="transcript_segment",
                            content_hash=digest,
                            provider="openai",
                            provider_version="long_interview_stt.i5",
                            quality_state="review_required",
                            confidence=normalize_provider_confidence(
                                result.confidence,
                                provider_supplied=result.confidence_provider_supplied,
                            ),
                            content=text,
                            metadata_json={
                                "chunk_index": chunk_index,
                                "language": result.language,
                                "start_ms": start_ms,
                                "end_ms": end_ms,
                                "candidate_only": True,
                                "source_provider": result.provider or "openai",
                                "source_provider_version": (
                                    result.provider_version or package_version("openai")
                                ),
                                "source_model": (
                                    result.model or settings.LONG_INTERVIEW_STT_MODEL
                                ),
                                "confidence_semantics": (
                                    "provider_supplied"
                                    if result.confidence_provider_supplied
                                    else "unknown"
                                ),
                                "confidence_provider_supplied": (
                                    result.confidence_provider_supplied
                                ),
                                "confidence_calibration_version": (
                                    result.confidence_calibration_version
                                    or "unavailable"
                                ),
                            },
                        )
                        db.add(artifact)
                        db.flush()
                    span = (
                        db.query(EvidenceSpan.id)
                        .filter(
                            EvidenceSpan.tenant_id == tenant_uuid,
                            EvidenceSpan.artifact_id == artifact.id,
                            EvidenceSpan.start_ms == start_ms,
                            EvidenceSpan.end_ms == end_ms,
                        )
                        .first()
                    )
                    if span is None:
                        db.add(
                            EvidenceSpan(
                                tenant_id=tenant_uuid,
                                artifact_id=artifact.id,
                                asset_revision_id=revision.id,
                                locator_kind="audio",
                                start_ms=start_ms,
                                end_ms=end_ms,
                                speaker=speaker,
                            )
                        )
                    artifact_ids.append(str(artifact.id))

                artifact_ids = list(dict.fromkeys(artifact_ids))
                orchestrator.transition(
                    db,
                    job,
                    to_status="running",
                    phase="transcript_partial",
                    readiness={
                        "searchable": False,
                        "partial": True,
                        "requires_human_review": True,
                        "completed_chunks": chunk_index + 1,
                        "total_chunks": len(chunks),
                        "progress_percent": round(
                            (chunk_index + 1) * 100 / len(chunks), 1
                        ),
                        "artifact_ids": artifact_ids,
                    },
                    details={
                        "completed_chunks": chunk_index + 1,
                        "total_chunks": len(chunks),
                    },
                )
                if analysis_run is not None:
                    from app.services.media_reliability import merge_checkpoint

                    analysis_run.checkpoint_json = merge_checkpoint(
                        dict(analysis_run.checkpoint_json or {}),
                        {
                            "phase": "transcript_partial",
                            "completed_chunk_index": chunk_index,
                            "completed_chunk_count": chunk_index + 1,
                            "total_chunk_count": len(chunks),
                        },
                    )
                db.commit()

        capability_results = audio_capability_results(
            job.requested_capabilities or [],
            transcript_count=len(artifact_ids),
            audio_chunk_count=len(chunks),
            preview_ready=bool(settings.MEDIA_PROXY_ENABLED),
            provider=(result.provider or "openai"),
            provider_version=result.provider_version,
            model=(result.model or settings.LONG_INTERVIEW_STT_MODEL),
            confidence_provider_supplied=result.confidence_provider_supplied,
            calibration_version=result.confidence_calibration_version,
        )
        if not artifact_ids:
            revision.ingestion_status = "ready"
            asset.status = "active"
            orchestrator.transition(
                db,
                job,
                to_status="ready",
                phase="completed_no_speech",
                quality_state="rejected",
                readiness=readiness_with_capability_results(
                    {
                        "searchable": False,
                        "partial": False,
                        "requires_human_review": False,
                        "reason": "no_speech_detected",
                        "artifact_ids": [],
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
                        "phase": "completed_no_speech",
                    },
                )
            db.commit()
            return {"job_id": job_id, "status": job.status, "artifact_ids": []}
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
                    "partial": False,
                    "requires_human_review": True,
                    "artifact_ids": artifact_ids,
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
                    "transcript_count": len(artifact_ids),
                    "quality_risks": list(audio_profile.risks) if audio_profile else [],
                    "precision_degraded_chunk_count": precision_degraded_chunks,
                },
            )
        db.commit()
        return {"job_id": job_id, "status": job.status, "artifact_ids": artifact_ids}
    except Exception as exc:
        db.rollback()
        logger.exception("audio processing failed: revision=%s", revision_id)
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
                    IngestionJob.tenant_id == tenant_uuid, IngestionJob.id == job_uuid
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
                        db, job, to_status="running", phase="audio_probe"
                    )
                get_ingestion_orchestrator().fail(
                    db,
                    job,
                    code=failure.code,
                    message=failure.technical_message,
                    phase="audio_processing",
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
                    asset.status = "failed" if exhausted else "processing"
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
            logger.exception("failed to persist audio task failure state")
        if failure.retryable and self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))
        raise
    finally:
        db.close()
