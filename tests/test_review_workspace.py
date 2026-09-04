from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models.asset import (
    ArtifactReviewDecision,
    AssetRevision,
    DerivedArtifact,
    EvidenceSpan,
    SourceAsset,
)
from app.models.audit import AuditLog
from app.models.review_item import ReviewItem
from app.models.ingestion import IngestionJob
from app.models.knowledge_unit import (
    KnowledgeUnitRecord,
    KnowledgeUnitRelease,
    KnowledgeUnitReleaseMembership,
    KnowledgeUnitRevision,
)
from app.services.review_workspace import (
    decide_source_group,
    group_review_items,
    list_review_items,
)


def _session():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=OFF")

    for table in (
        SourceAsset.__table__,
        AssetRevision.__table__,
        DerivedArtifact.__table__,
        EvidenceSpan.__table__,
        IngestionJob.__table__,
        ReviewItem.__table__,
        ArtifactReviewDecision.__table__,
        KnowledgeUnitRecord.__table__,
        KnowledgeUnitRevision.__table__,
        KnowledgeUnitRelease.__table__,
        KnowledgeUnitReleaseMembership.__table__,
        AuditLog.__table__,
    ):
        table.create(engine, checkfirst=True)
    return engine, sessionmaker(bind=engine)()


def _user(tenant_id, user_id):
    return SimpleNamespace(
        tenant_id=tenant_id,
        id=user_id,
        role="admin",
        is_superuser=False,
        department_id=None,
    )


def test_review_inbox_preserves_locator_and_allows_creator_to_confirm_literal_text(
    monkeypatch,
):
    monkeypatch.setattr(settings, "PACK_MKA_ENABLED", False)
    engine, db = _session()
    tenant_id, creator_id, reviewer_id = uuid4(), uuid4(), uuid4()
    try:
        asset = SourceAsset(
            tenant_id=tenant_id,
            asset_kind="audio",
            title="交接錄音",
            source_system="upload",
            data_classification="internal",
            acl_reference={
                "visibility": "tenant",
                "owner_subject_id": str(creator_id),
                "policy_revision": 1,
            },
            current_revision=1,
            status="review_required",
            created_by=creator_id,
        )
        db.add(asset)
        db.flush()
        revision = AssetRevision(
            tenant_id=tenant_id,
            asset_id=asset.id,
            revision=1,
            media_type="audio/wav",
            content_uri="object://audio.wav",
            content_hash="a" * 64,
            ingestion_status="review_required",
            created_by=creator_id,
        )
        db.add(revision)
        db.flush()
        db.add(
            IngestionJob(
                tenant_id=tenant_id,
                asset_revision_id=revision.id,
                status="review_required",
                phase="human_review",
                adapter_key="test.audio",
                adapter_version="1",
                requested_capabilities=[],
                idempotency_key="review-workspace-test",
                readiness={},
                error={},
            )
        )
        artifact = DerivedArtifact(
            tenant_id=tenant_id,
            asset_revision_id=revision.id,
            artifact_kind="transcript_segment",
            content_hash="b" * 64,
            provider="test",
            provider_version="1",
            quality_state="review_required",
            confidence=0.72,
            content="壓力歸零後才能開門",
            metadata_json={},
        )
        db.add(artifact)
        db.flush()
        db.add(
            EvidenceSpan(
                tenant_id=tenant_id,
                artifact_id=artifact.id,
                asset_revision_id=revision.id,
                locator_kind="audio",
                start_ms=642_000,
                end_ms=678_000,
            )
        )
        db.commit()

        creator_item = list_review_items(
            db, current_user=_user(tenant_id, creator_id)
        )[0]
        assert "separation_of_duty" not in creator_item["blocked_reasons"]
        assert creator_item["batch_eligible"] is False
        group = group_review_items([creator_item])[0]
        assert group["source_confirmable_count"] == 1
        assert group["exception_count"] == 0
        assert group["source_approval_ready"] is True

        reviewer_item = list_review_items(
            db, current_user=_user(tenant_id, reviewer_id)
        )[0]
        assert reviewer_item["id"] == f"artifact:{artifact.id}"
        assert reviewer_item["source_group_key"] == f"asset:{asset.id}"
        assert reviewer_item["evidence"][0]["start_ms"] == 642_000
        assert "t=642000" in reviewer_item["evidence"][0]["deep_link"]
        assert reviewer_item["evidence"][0]["deep_link"].endswith("end=678000")
        assert reviewer_item["batch_eligible"] is False  # low confidence
    finally:
        db.close()
        engine.dispose()


def test_legacy_items_remain_available_through_generic_contract(monkeypatch):
    monkeypatch.setattr(settings, "PACK_MKA_ENABLED", False)
    engine, db = _session()
    tenant_id = uuid4()
    try:
        item = ReviewItem(
            tenant_id=tenant_id,
            file_path="C:/watch/manual.pdf",
            file_name="manual.pdf",
            suggested_category="SOP",
            suggested_tags={},
            confidence_score=0.95,
            status="pending",
        )
        db.add(item)
        db.commit()
        result = list_review_items(
            db, current_user=_user(tenant_id, uuid4())
        )
        assert result[0]["id"] == f"legacy:{item.id}"
        assert result[0]["source_type"] == "document_classification"
        assert result[0]["batch_eligible"] is False
        assert result[0]["publication"]["acl"]["policy_revision"] == 1
    finally:
        db.close()
        engine.dispose()


def test_source_confirmation_publishes_literal_text_but_leaves_inference_pending(
    monkeypatch,
):
    monkeypatch.setattr(settings, "PACK_MKA_ENABLED", False)
    engine, db = _session()
    tenant_id, owner_id = uuid4(), uuid4()
    user = _user(tenant_id, owner_id)
    try:
        asset = SourceAsset(
            tenant_id=tenant_id,
            asset_kind="video",
            title="設備教育影片",
            source_system="upload",
            data_classification="internal",
            acl_reference={"visibility": "tenant", "policy_revision": 1},
            current_revision=1,
            status="review_required",
            created_by=owner_id,
        )
        db.add(asset)
        db.flush()
        revision = AssetRevision(
            tenant_id=tenant_id,
            asset_id=asset.id,
            revision=1,
            media_type="video/mp4",
            content_uri="object://training.mp4",
            content_hash="c" * 64,
            ingestion_status="review_required",
            created_by=owner_id,
        )
        db.add(revision)
        db.flush()
        db.add(
            IngestionJob(
                tenant_id=tenant_id,
                asset_revision_id=revision.id,
                status="review_required",
                phase="human_review",
                adapter_key="test.video",
                adapter_version="1",
                requested_capabilities=[],
                idempotency_key=f"source-confirm-{uuid4()}",
                readiness={},
                error={},
            )
        )
        transcript = DerivedArtifact(
            tenant_id=tenant_id,
            asset_revision_id=revision.id,
            artifact_kind="transcript_segment",
            content_hash="d" * 64,
            provider="test",
            provider_version="1",
            quality_state="review_required",
            confidence=0.71,
            content="確認壓力歸零",
            metadata_json={},
        )
        procedure = DerivedArtifact(
            tenant_id=tenant_id,
            asset_revision_id=revision.id,
            artifact_kind="procedure_candidate",
            content_hash="e" * 64,
            provider="test",
            provider_version="1",
            quality_state="review_required",
            confidence=0.4,
            content='{"steps": []}',
            metadata_json={},
        )
        db.add_all([transcript, procedure])
        db.flush()
        for target in (transcript, procedure):
            db.add(
                EvidenceSpan(
                    tenant_id=tenant_id,
                    artifact_id=target.id,
                    asset_revision_id=revision.id,
                    locator_kind="video",
                    start_ms=0,
                    end_ms=2000,
                )
            )
        db.commit()

        items = list_review_items(db, current_user=user)
        group = group_review_items(items)[0]
        assert group["source_confirmable_count"] == 1
        assert group["exception_count"] == 1

        result = decide_source_group(
            db,
            current_user=user,
            source_asset_id=asset.id,
            payload={
                "decision": "approved",
                "acknowledge_low_confidence": True,
                "notes": "已對照原始影片",
            },
        )
        assert result["decided_count"] == 1
        db.refresh(transcript)
        db.refresh(procedure)
        assert transcript.quality_state == "ready"
        assert procedure.quality_state == "review_required"
        unit_revision = db.query(KnowledgeUnitRevision).one()
        assert unit_revision.metadata_json["locator"]["start_ms"] == 0
        assert "evidence=" in unit_revision.metadata_json["deep_link"]
        assert unit_revision.metadata_json["deep_link"].endswith("&t=0&end=2000")
    finally:
        db.close()
        engine.dispose()
