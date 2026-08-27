from __future__ import annotations

import json
import subprocess
from array import array
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.api.v1.endpoints.video_assets import (
    ArtifactReviewRequest,
    review_video_procedure,
)
from app.composition.ingestion import build_ingestion_adapter_registry
from app.core.authorization import AuthorizationContext
from app.ingestion.video_knowledge_provider import ApprovedVideoProcedureProvider
from app.models.asset import (
    ArtifactReviewDecision,
    AssetRevision,
    DerivedArtifact,
    EvidenceSpan,
    SourceAsset,
)
from app.models.ingestion import IngestionJob, IngestionJobEvent
from app.models.knowledge_unit import (
    KnowledgeUnitRecord,
    KnowledgeUnitRelease,
    KnowledgeUnitReleaseMembership,
    KnowledgeUnitRevision,
)
from app.models.mka import JobRole
from app.models.permission import Department
from app.models.tenant import Tenant
from app.models.user import User
from app.platform.ingestion import IngestionRequest
from app.platform.knowledge import KnowledgeProviderRegistry
from app.platform.multimodal import MultimodalAnalysisContext
from app.services.media_access import create_media_token, decode_media_token
from app.services.video_governance import (
    apply_sop_precedence,
    build_sop_conflict_report,
    build_structured_procedure,
    project_governed_video_procedure,
)
from app.services.video_processing import (
    VideoKeyframe,
    VideoProbe,
    VideoProcessingResult,
    VideoTranscriptSegment,
    extract_keyframes,
    parse_probe_payload,
    process_video_file,
    project_video_result,
)
from app.services.video_understanding import (
    AudioSignalOutlierProvider,
    EvidenceRuleTimelineProvider,
    MultimodalProviderRegistry,
    analyze_multimodal_timeline,
    parse_scene_showinfo,
    project_multimodal_timeline,
)


def test_production_runtime_includes_ffmpeg_toolchain():
    dockerfile = Path(__file__).resolve().parents[1] / "Dockerfile"
    content = dockerfile.read_text(encoding="utf-8")

    assert "\n    ffmpeg \\\n" in content


def test_production_runtime_includes_only_the_p3_synthetic_corpus_contract():
    dockerignore = Path(__file__).resolve().parents[1] / ".dockerignore"
    content = dockerignore.read_text(encoding="utf-8")

    assert "!scripts/capture_p3_staging_replay.py" in content
    assert "!testdata/multimodal_golden/manifest.json" in content
    assert "!testdata/multimodal_golden/ground_truth.schema.json" in content
    assert "!testdata/golden/" not in content


@pytest.fixture()
def video_db():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    for table in (
        Tenant.__table__,
        Department.__table__,
        JobRole.__table__,
        User.__table__,
        SourceAsset.__table__,
        AssetRevision.__table__,
        DerivedArtifact.__table__,
        EvidenceSpan.__table__,
        IngestionJob.__table__,
        IngestionJobEvent.__table__,
        ArtifactReviewDecision.__table__,
        KnowledgeUnitRecord.__table__,
        KnowledgeUnitRevision.__table__,
        KnowledgeUnitRelease.__table__,
        KnowledgeUnitReleaseMembership.__table__,
    ):
        table.create(engine, checkfirst=True)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _video_source(db, *, role="admin"):
    tenant = Tenant(name=f"tenant-{uuid4().hex[:6]}")
    db.add(tenant)
    db.flush()
    user = User(
        tenant_id=tenant.id,
        email=f"{uuid4().hex}@example.invalid",
        hashed_password="x",
        role=role,
        status="active",
    )
    db.add(user)
    db.flush()
    asset = SourceAsset(
        tenant_id=tenant.id,
        asset_kind="video",
        title="Machine reset",
        source_system="upload",
        current_revision=1,
        status="review_required",
        created_by=user.id,
    )
    db.add(asset)
    db.flush()
    revision = AssetRevision(
        tenant_id=tenant.id,
        asset_id=asset.id,
        revision=1,
        media_type="video/mp4",
        content_uri="s3://bucket/video.mp4",
        content_hash="a" * 64,
        duration_ms=30_000,
        ingestion_status="review_required",
        created_by=user.id,
    )
    db.add(revision)
    db.flush()
    return tenant, user, asset, revision


def _result() -> VideoProcessingResult:
    return VideoProcessingResult(
        probe=VideoProbe(
            duration_ms=30_000,
            width=1920,
            height=1080,
            video_codec="h264",
            audio_codec="aac",
            frame_rate=30.0,
            format_name="mov,mp4",
        ),
        transcript_segments=[
            VideoTranscriptSegment(
                start_ms=1_000,
                end_ms=4_000,
                text="先確認壓力歸零",
                speaker="師傅",
                confidence=0.9,
            ),
            VideoTranscriptSegment(
                start_ms=4_000,
                end_ms=7_000,
                text="再解除安全門鎖",
                speaker="師傅",
                confidence=0.88,
            ),
        ],
        keyframes=[
            VideoKeyframe(
                timestamp_ms=2_000,
                frame_index=60,
                path="frame.jpg",
                ocr_text="壓力 0 bar",
                ocr_confidence=0.92,
                artifact_uri="s3://bucket/frame.jpg",
                storage_key="00000000-0000-0000-0000-000000000000/frame.jpg",
            )
        ],
        audio_chunk_count=1,
    )


def test_probe_parser_extracts_video_audio_and_fractional_rate():
    probe = parse_probe_payload(
        {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080,
                    "avg_frame_rate": "30000/1001",
                },
                {"codec_type": "audio", "codec_name": "aac"},
            ],
            "format": {"duration": "12.5", "format_name": "mov,mp4"},
        }
    )

    assert probe.duration_ms == 12_500
    assert probe.has_audio
    assert probe.video_codec == "h264"
    assert probe.frame_rate == pytest.approx(29.97, rel=0.001)


def test_processing_demuxes_timestamps_keyframes_and_ocr(tmp_path):
    def runner(command, *, timeout):
        output = command[-1]
        if "%04d" in output:
            Path(output.replace("%04d", "0000")).write_bytes(b"audio")
        elif output.endswith(".jpg"):
            Path(output).write_bytes(b"jpeg")
        return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")

    result = process_video_file(
        "source.mp4",
        str(tmp_path),
        probe=VideoProbe(30_000, 1920, 1080, "h264", "aac", 30.0, "mp4"),
        runner=runner,
        stt=lambda _path: (
            [{"start": 1, "end": 2.5, "text": "確認壓力", "speaker": "A"}],
            0.9,
        ),
        ocr=lambda _path: ("壓力 0 bar", 0.95),
    )

    assert result.audio_chunk_count == 1
    assert result.transcript_segments[0].start_ms == 1_000
    assert result.transcript_segments[0].end_ms == 2_500
    assert len(result.keyframes) == 2
    assert result.keyframes[0].ocr_text == "壓力 0 bar"


def test_keyframe_extraction_stays_inside_last_decodable_frame(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.VIDEO_KEYFRAME_MIN_INTERVAL_SECONDS", 15)
    monkeypatch.setattr("app.config.settings.VIDEO_MAX_KEYFRAMES", 10)
    seeks = []

    def runner(command, *, timeout):
        seeks.append(float(command[command.index("-ss") + 1]))
        Path(command[-1]).write_bytes(b"jpeg")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    frames = extract_keyframes(
        "source.mp4",
        str(tmp_path),
        VideoProbe(15_045, 640, 360, "h264", "aac", 24.0, "mp4"),
        runner=runner,
    )

    assert len(frames) == 2
    assert seeks == [0.0, 14.795]
    assert seeks[-1] < 15.045


def test_scene_boundaries_become_bounded_timeline_observations():
    rows = parse_scene_showinfo(
        "frame:1 pts_time:2.500 scene:0.41\nframe:2 pts_time:7.000 scene:0.62",
        duration_ms=10_000,
        frame_rate=25.0,
    )

    assert [(row.start_ms, row.end_ms) for row in rows] == [
        (0, 2_500),
        (2_500, 7_000),
        (7_000, 10_000),
    ]
    assert rows[1].frame_index == 62
    assert rows[0].provider == "core.ffmpeg_scene"


def test_evidence_rules_do_not_invent_speakers_and_label_candidate_methods():
    result = _result()
    output = EvidenceRuleTimelineProvider().analyze(
        MultimodalAnalysisContext(
            video_path="source.mp4",
            duration_ms=result.probe.duration_ms,
            frame_rate=result.probe.frame_rate,
            has_audio=result.probe.has_audio,
            transcript_segments=tuple(result.transcript_segments),
            keyframes=tuple(result.keyframes),
        )
    )

    assert output.capability_states["speaker_diarization"] == "available_upstream"
    assert any(
        row.kind == "speaker_turn" and row.speaker == "師傅"
        for row in output.observations
    )
    assert any(row.kind == "action_event" for row in output.observations)
    visual_state = next(
        row
        for row in output.observations
        if row.kind == "equipment_state" and row.label.startswith("visual")
    )
    assert visual_state.attributes["detection_method"] == "ocr_state_or_measurement"
    assert visual_state.attributes["measurements"][0]["unit"].lower() == "bar"


def test_english_high_risk_terms_are_classified_for_multilingual_procedures(video_db):
    _, _, _, revision = _video_source(video_db)
    result = _result()
    result.transcript_segments[0] = VideoTranscriptSegment(
        start_ms=1_000,
        end_ms=4_000,
        text="Danger: force reset EQ-100 only after pressure is zero",
        speaker="operator",
        confidence=0.9,
    )
    project_video_result(video_db, revision, result)

    procedure = build_structured_procedure(video_db, revision)

    assert procedure is not None
    assert procedure.payload["risks"]
    assert procedure.payload["decision_rules"]


def test_audio_signal_provider_emits_non_diagnostic_outlier_candidate():
    samples = array("h", [1000] * 8000 + [1000] * 8000 + [10000] * 8000)

    def runner(*_args, **_kwargs):
        return subprocess.CompletedProcess([], 0, stdout=samples.tobytes(), stderr=b"")

    output = AudioSignalOutlierProvider(runner=runner).analyze(
        MultimodalAnalysisContext(
            video_path="source.mp4",
            duration_ms=3_000,
            frame_rate=30.0,
            has_audio=True,
            transcript_segments=(),
            keyframes=(),
        )
    )

    assert output.capability_states["audio_anomaly"] == "candidate_signal_outlier"
    assert len(output.observations) == 1
    assert output.observations[0].start_ms == 2_000
    assert output.observations[0].attributes["semantic_diagnosis"] is False


def test_multimodal_registry_isolates_provider_failure_and_fails_closed():
    class BrokenAudioProvider:
        provider_key = "tenant.audio_anomaly"
        provider_version = "1.0"
        capability_keys = ("audio_anomaly",)
        execution_boundary = "tenant_provider"

        def analyze(self, _context):
            raise RuntimeError("provider offline")

    result = _result()
    understanding = analyze_multimodal_timeline(
        "source.mp4",
        result,
        registry=MultimodalProviderRegistry(
            [EvidenceRuleTimelineProvider(), BrokenAudioProvider()]
        ),
    )

    assert understanding.capability_states["audio_anomaly"] == "failed"
    assert understanding.provider_failures == [
        {"provider": "tenant.audio_anomaly", "error": "provider offline"}
    ]
    assert any(row.kind == "action_event" for row in understanding.observations)


def test_multimodal_projection_preserves_provider_and_exact_evidence(video_db):
    _, _, _, revision = _video_source(video_db)
    result = _result()
    project_video_result(video_db, revision, result)
    understanding = analyze_multimodal_timeline(
        "source.mp4",
        result,
        registry=MultimodalProviderRegistry([EvidenceRuleTimelineProvider()]),
    )
    summary = project_multimodal_timeline(video_db, revision, understanding)

    assert summary["capability_states"]["audio_anomaly"] == "unavailable"
    action = (
        video_db.query(DerivedArtifact)
        .filter(DerivedArtifact.artifact_kind == "action_event")
        .first()
    )
    assert action is not None
    assert action.provider == "core.evidence_rules"
    span = (
        video_db.query(EvidenceSpan).filter(EvidenceSpan.artifact_id == action.id).one()
    )
    assert span.locator_kind == "video"
    assert span.start_ms == 1_000
    timeline = (
        video_db.query(DerivedArtifact)
        .filter(DerivedArtifact.artifact_kind == "timeline_alignment")
        .one()
    )
    assert '"audio_anomaly": "unavailable"' in timeline.content
    timeline_payload = json.loads(timeline.content)
    aligned_kinds = {
        entry["kind"]
        for window in timeline_payload["windows"]
        for entry in window["entries"]
    }
    assert {"transcript_segment", "keyframe", "action_event"} <= aligned_kinds


def test_structured_procedure_classifies_only_evidence_backed_fields(video_db):
    _, _, _, revision = _video_source(video_db)
    result = _result()
    result.transcript_segments.extend(
        [
            VideoTranscriptSegment(
                7_000, 8_000, "如果壓力未歸零則必須停機", "師傅", 0.87
            ),
            VideoTranscriptSegment(
                8_000, 9_000, "注意夾傷，禁止短接安全迴路", "師傅", 0.94
            ),
            VideoTranscriptSegment(9_000, 10_000, "異常時由主管確認", "師傅", 0.89),
        ]
    )
    project_video_result(video_db, revision, result, create_procedure_candidate=False)
    structured = build_structured_procedure(video_db, revision)

    assert structured is not None
    assert structured.payload["steps"][0]["evidence_artifact_id"]
    assert structured.payload["decision_rules"][0]["text"].startswith("如果")
    assert "夾傷" in structured.payload["risks"][0]["text"]
    assert "禁止" in structured.payload["prohibited_actions"][0]["text"]
    assert structured.payload["exceptions"][0]["deep_link"].endswith("?t=9000")


def test_sop_precedence_replaces_conflicting_step_in_published_projection():
    procedure = {
        "steps": [
            {"sequence": 1, "text": "解除安全門鎖"},
        ],
        "prohibited_actions": [],
    }
    report = build_sop_conflict_report(
        procedure,
        [
            {
                "id": "sop-1",
                "revision": 3,
                "title": "正式復歸 SOP",
                "steps": [],
                "applicable_equipment": [],
                "cautions": ["禁止解除安全門鎖"],
                "evidence": [
                    {
                        "document_id": "sop-1",
                        "document_revision": 3,
                        "chunk_id": "chunk-8",
                        "chunk_index": 8,
                        "text": "禁止解除安全門鎖",
                    }
                ],
            }
        ],
    )
    assert len(report["conflicts"]) == 1
    conflict = report["conflicts"][0]
    assert conflict["sop_evidence"]["chunk_id"] == "chunk-8"

    published, unresolved = apply_sop_precedence(
        procedure,
        report["conflicts"],
        {conflict["id"]: "sop_wins"},
    )
    assert unresolved == []
    assert published["steps"][0]["text"] == "禁止解除安全門鎖"
    assert published["steps"][0]["authority_override"] == "formal_sop"


def test_review_blocks_unresolved_sop_conflict_then_publishes_sop_winner(video_db):
    tenant, reviewer, _, revision = _video_source(video_db)
    result = _result()
    project_video_result(video_db, revision, result, create_procedure_candidate=False)
    understanding = analyze_multimodal_timeline(
        "source.mp4",
        result,
        registry=MultimodalProviderRegistry([EvidenceRuleTimelineProvider()]),
    )
    project_multimodal_timeline(video_db, revision, understanding)
    projection = project_governed_video_procedure(
        video_db,
        revision,
        sop_documents=[
            {
                "id": "sop-1",
                "revision": 3,
                "title": "正式復歸 SOP",
                "steps": [],
                "applicable_equipment": [],
                "cautions": ["禁止解除安全門鎖"],
            }
        ],
    )
    artifact = video_db.get(DerivedArtifact, UUID(projection["procedure_artifact_id"]))
    report_artifact = video_db.get(
        DerivedArtifact, UUID(projection["conflict_report_artifact_id"])
    )
    conflicts = json.loads(report_artifact.content)["conflicts"]
    assert conflicts
    assert report_artifact.metadata_json["procedure_artifact_id"] == str(artifact.id)
    job = IngestionJob(
        tenant_id=tenant.id,
        asset_revision_id=revision.id,
        adapter_key="core.video",
        adapter_version="1.0",
        requested_capabilities=["procedure_candidate"],
        idempotency_key="governed-video-review",
        status="review_required",
        phase="human_review",
        attempt=1,
        quality_state="review_required",
    )
    video_db.add(job)
    video_db.flush()

    with pytest.raises(HTTPException) as blocked:
        review_video_procedure(
            artifact.id,
            ArtifactReviewRequest(decision="approved"),
            video_db,
            reviewer,
        )
    assert "unresolved_sop_conflicts" in str(blocked.value)

    response = review_video_procedure(
        artifact.id,
        ArtifactReviewRequest(
            decision="approved",
            conflict_resolutions={row["id"]: "sop_wins" for row in conflicts},
        ),
        video_db,
        reviewer,
    )
    assert response["searchable"] is True
    decision = (
        video_db.query(ArtifactReviewDecision)
        .filter(ArtifactReviewDecision.artifact_id == artifact.id)
        .one()
    )
    assert (
        decision.resolution_json["published_procedure"]["steps"][1]["text"]
        == "禁止解除安全門鎖"
    )
    authz = AuthorizationContext(
        tenant_id=tenant.id, subject_id=reviewer.id, role_ids=["admin"]
    )
    rows = (
        KnowledgeProviderRegistry([ApprovedVideoProcedureProvider()])
        .contribute(authz=authz, query="復歸", db=video_db, top_k=5)
        .to_retrieval_dicts()
    )
    assert "禁止解除安全門鎖" in rows[0]["content"]
    assert "再解除安全門鎖" not in rows[0]["content"]


def test_high_risk_video_requires_explicit_reviewer_acknowledgement(video_db):
    tenant, reviewer, _, revision = _video_source(video_db)
    result = _result()
    result.transcript_segments.append(
        VideoTranscriptSegment(
            7_000,
            9_000,
            "注意夾傷，禁止短接安全迴路",
            "師傅",
            0.95,
        )
    )
    project_video_result(video_db, revision, result, create_procedure_candidate=False)
    projection = project_governed_video_procedure(video_db, revision, sop_documents=[])
    artifact = video_db.get(DerivedArtifact, UUID(projection["procedure_artifact_id"]))
    video_db.add(
        IngestionJob(
            tenant_id=tenant.id,
            asset_revision_id=revision.id,
            adapter_key="core.video",
            adapter_version="1.0",
            requested_capabilities=["procedure_candidate"],
            idempotency_key="high-risk-video-review",
            status="review_required",
            phase="human_review",
            attempt=1,
            quality_state="review_required",
        )
    )
    video_db.flush()

    with pytest.raises(HTTPException) as blocked:
        review_video_procedure(
            artifact.id,
            ArtifactReviewRequest(decision="approved"),
            video_db,
            reviewer,
        )
    assert "high_risk_acknowledgement_required" in str(blocked.value)

    response = review_video_procedure(
        artifact.id,
        ArtifactReviewRequest(decision="approved", acknowledge_high_risk=True),
        video_db,
        reviewer,
    )
    assert response["searchable"] is True
    decision = (
        video_db.query(ArtifactReviewDecision)
        .filter(ArtifactReviewDecision.artifact_id == artifact.id)
        .one()
    )
    assert decision.resolution_json["acknowledged_high_risk"] is True


def test_video_without_evidence_finishes_without_review_candidate(video_db):
    _, _, _, revision = _video_source(video_db)
    projection = project_governed_video_procedure(video_db, revision, sop_documents=[])
    assert projection == {
        "procedure_artifact_id": None,
        "conflict_count": 0,
        "high_risk": False,
    }


def test_projection_creates_temporal_lineage_and_review_candidate(video_db):
    _, _, _, revision = _video_source(video_db)
    summary = project_video_result(video_db, revision, _result())

    assert summary == {
        "transcript_count": 2,
        "keyframe_count": 1,
        "ocr_count": 1,
        "procedure_artifact_id": summary["procedure_artifact_id"],
    }
    procedure = (
        video_db.query(DerivedArtifact)
        .filter(DerivedArtifact.artifact_kind == "procedure_candidate")
        .one()
    )
    assert procedure.quality_state == "review_required"
    assert '"deep_link": "/knowledge/videos/' in procedure.content
    evidence = (
        video_db.query(EvidenceSpan)
        .filter(EvidenceSpan.artifact_id == procedure.id)
        .one()
    )
    assert evidence.locator_kind == "video"
    assert (evidence.start_ms, evidence.end_ms) == (1_000, 7_000)

    again = project_video_result(video_db, revision, _result())
    assert again == summary
    assert (
        video_db.query(DerivedArtifact)
        .filter(DerivedArtifact.artifact_kind == "procedure_candidate")
        .count()
        == 1
    )


def test_human_approval_publishes_candidate_to_core_retrieval(video_db):
    tenant, reviewer, _, revision = _video_source(video_db)
    summary = project_video_result(video_db, revision, _result())
    artifact = video_db.get(DerivedArtifact, UUID(summary["procedure_artifact_id"]))
    job = IngestionJob(
        tenant_id=tenant.id,
        asset_revision_id=revision.id,
        adapter_key="core.video",
        adapter_version="1.0",
        requested_capabilities=["procedure_candidate"],
        idempotency_key="video-review",
        status="review_required",
        phase="human_review",
        attempt=1,
        quality_state="review_required",
    )
    video_db.add(job)
    video_db.flush()

    response = review_video_procedure(
        artifact.id,
        ArtifactReviewRequest(decision="approved", notes="畫面與步驟已核對"),
        video_db,
        reviewer,
    )

    assert response["searchable"] is True
    assert artifact.quality_state == "ready"
    assert job.status == "ready"
    decision = (
        video_db.query(ArtifactReviewDecision)
        .filter(ArtifactReviewDecision.artifact_id == artifact.id)
        .one()
    )
    authority = decision.resolution_json["knowledge_authority"]
    assert authority["idempotent"] is False
    assert video_db.query(KnowledgeUnitRecord).count() == 1
    assert video_db.query(KnowledgeUnitRevision).count() == 1
    assert (
        video_db.query(KnowledgeUnitRelease)
        .filter(KnowledgeUnitRelease.status == "active")
        .count()
        == 1
    )
    assert video_db.query(KnowledgeUnitReleaseMembership).count() == 1
    authz = AuthorizationContext(
        tenant_id=tenant.id, subject_id=reviewer.id, role_ids=["admin"]
    )
    batch = KnowledgeProviderRegistry([ApprovedVideoProcedureProvider()]).contribute(
        authz=authz, query="機台如何復歸", db=video_db, top_k=5
    )
    rows = batch.to_retrieval_dicts()
    assert len(rows) == 1
    assert "先確認壓力歸零" in rows[0]["content"]
    assert rows[0]["metadata"]["deep_link"].startswith("/knowledge/videos/")


def test_video_provider_revalidates_asset_acl(video_db):
    tenant, reviewer, asset, revision = _video_source(video_db)
    summary = project_video_result(video_db, revision, _result())
    artifact = video_db.get(DerivedArtifact, UUID(summary["procedure_artifact_id"]))
    video_db.add(
        IngestionJob(
            tenant_id=tenant.id,
            asset_revision_id=revision.id,
            adapter_key="core.video",
            adapter_version="1.0",
            requested_capabilities=["procedure_candidate"],
            idempotency_key="video-private-review",
            status="review_required",
            phase="human_review",
            attempt=1,
            quality_state="review_required",
        )
    )
    video_db.flush()
    review_video_procedure(
        artifact.id,
        ArtifactReviewRequest(decision="approved"),
        video_db,
        reviewer,
    )
    asset.acl_reference = {
        "schema_version": "1.0",
        "policy_revision": 1,
        "visibility": "private",
        "owner_subject_id": str(reviewer.id),
    }
    outsider = User(
        tenant_id=tenant.id,
        email=f"{uuid4().hex}@example.invalid",
        hashed_password="x",
        role="employee",
        status="active",
    )
    video_db.add(outsider)
    video_db.flush()

    hidden = KnowledgeProviderRegistry([ApprovedVideoProcedureProvider()]).contribute(
        authz=AuthorizationContext.from_user(outsider),
        query="機台如何復歸",
        db=video_db,
        top_k=5,
    )
    assert hidden.candidates == ()


def test_review_decision_composite_fk_rejects_cross_tenant_artifact(video_db):
    tenant_a, _, _, revision = _video_source(video_db)
    summary = project_video_result(video_db, revision, _result())
    artifact = video_db.get(DerivedArtifact, UUID(summary["procedure_artifact_id"]))
    tenant_b, reviewer_b, _, _ = _video_source(video_db)
    assert tenant_a.id != tenant_b.id
    video_db.add(
        ArtifactReviewDecision(
            tenant_id=tenant_b.id,
            artifact_id=artifact.id,
            asset_revision_id=revision.id,
            decision="approved",
            reviewer_id=reviewer_b.id,
        )
    )
    with pytest.raises(IntegrityError):
        video_db.flush()


def test_video_adapter_routes_complete_capability_request():
    request = IngestionRequest(
        tenant_id="tenant",
        asset_id="asset",
        asset_revision_id="revision",
        asset_kind="video",
        media_type="video/mp4",
        content_uri="s3://bucket/video.mp4",
        requested_capabilities=(
            "probe_metadata",
            "demux_audio",
            "transcribe",
            "timestamp",
            "keyframe",
            "ocr",
            "procedure_candidate",
        ),
    )
    assert (
        build_ingestion_adapter_registry().select(request).adapter_key == "core.video"
    )


def test_media_token_is_tenant_and_resource_bound():
    tenant_id = uuid4()
    user_id = uuid4()
    asset_id = uuid4()
    token = create_media_token(
        tenant_id=tenant_id,
        user_id=user_id,
        resource_kind="video",
        resource_id=asset_id,
    )

    claims = decode_media_token(token, resource_kind="video", resource_id=asset_id)
    assert claims is not None
    assert claims["tenant_id"] == str(tenant_id)
    assert claims["sub"] == str(user_id)
    assert decode_media_token(token, resource_kind="video", resource_id=uuid4()) is None
    assert (
        decode_media_token(token, resource_kind="video_artifact", resource_id=asset_id)
        is None
    )


def test_expired_media_token_is_rejected():
    import jwt

    from app.config import settings

    asset_id = uuid4()
    token = jwt.encode(
        {
            "exp": datetime.now(UTC) - timedelta(seconds=1),
            "sub": str(uuid4()),
            "tenant_id": str(uuid4()),
            "scope": "media.read",
            "resource_kind": "video",
            "resource_id": str(asset_id),
        },
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    assert (
        decode_media_token(token, resource_kind="video", resource_id=asset_id) is None
    )


def test_phase_f_migration_renders_upgrade_and_downgrade():
    from app.db.migrations.versions import video_artifact_review_f1_009 as migration

    upgrade_buffer = StringIO()
    context = MigrationContext.configure(
        url="postgresql://", opts={"as_sql": True, "output_buffer": upgrade_buffer}
    )
    with Operations.context(context):
        migration.upgrade()
    downgrade_buffer = StringIO()
    context = MigrationContext.configure(
        url="postgresql://", opts={"as_sql": True, "output_buffer": downgrade_buffer}
    )
    with Operations.context(context):
        migration.downgrade()

    assert "artifact_review_decisions" in upgrade_buffer.getvalue()
    assert "DROP TABLE artifact_review_decisions" in downgrade_buffer.getvalue()


def test_phase_f2_migration_replaces_artifact_kind_constraint():
    from app.db.migrations.versions import multimodal_timeline_f2_010 as migration

    upgrade_buffer = StringIO()
    context = MigrationContext.configure(
        url="postgresql://", opts={"as_sql": True, "output_buffer": upgrade_buffer}
    )
    with Operations.context(context):
        migration.upgrade()
    downgrade_buffer = StringIO()
    context = MigrationContext.configure(
        url="postgresql://", opts={"as_sql": True, "output_buffer": downgrade_buffer}
    )
    with Operations.context(context):
        migration.downgrade()

    assert "action_event" in upgrade_buffer.getvalue()
    assert "timeline_alignment" in upgrade_buffer.getvalue()
    assert "action_event" not in downgrade_buffer.getvalue()


def test_phase_f3_migration_adds_resolution_and_conflict_artifact():
    from app.db.migrations.versions import video_governance_f3_011 as migration

    upgrade_buffer = StringIO()
    context = MigrationContext.configure(
        url="postgresql://", opts={"as_sql": True, "output_buffer": upgrade_buffer}
    )
    with Operations.context(context):
        migration.upgrade()
    downgrade_buffer = StringIO()
    context = MigrationContext.configure(
        url="postgresql://", opts={"as_sql": True, "output_buffer": downgrade_buffer}
    )
    with Operations.context(context):
        migration.downgrade()

    assert "resolution_json" in upgrade_buffer.getvalue()
    assert "sop_conflict_report" in upgrade_buffer.getvalue()
    assert "DROP COLUMN resolution_json" in downgrade_buffer.getvalue()
