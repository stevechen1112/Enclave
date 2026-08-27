from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.orm import sessionmaker

from app.models.asset import AssetRevision, DerivedArtifact, EvidenceSpan, SourceAsset
from app.models.audit import AuditLog
from app.models.ingestion import IngestionJob
from app.models.knowledge_unit import KnowledgeUnitRecord
from app.models.user import User


@pytest.mark.anyio
async def test_generic_review_decision_is_evidence_backed_and_fail_closed(
    client: AsyncClient,
    superuser_headers: dict,
    test_engine,
):
    Session = sessionmaker(bind=test_engine)
    db = Session()
    try:
        reviewer = db.query(User).filter(User.email == "superuser@test.com").one()
        creator = User(
            tenant_id=reviewer.tenant_id,
            email=f"creator-{uuid4().hex}@example.invalid",
            hashed_password="x",
            role="admin",
            status="active",
        )
        db.add(creator)
        db.flush()
        asset = SourceAsset(
            tenant_id=reviewer.tenant_id,
            asset_kind="audio",
            title="夜班交接錄音",
            source_system="upload",
            data_classification="confidential",
            acl_reference={
                "visibility": "tenant",
                "owner_subject_id": str(creator.id),
                "policy_revision": 1,
            },
            current_revision=1,
            status="review_required",
            created_by=creator.id,
        )
        db.add(asset)
        db.flush()
        revision = AssetRevision(
            tenant_id=reviewer.tenant_id,
            asset_id=asset.id,
            revision=1,
            media_type="audio/wav",
            content_uri="object://night-shift.wav",
            content_hash="c" * 64,
            ingestion_status="review_required",
            created_by=creator.id,
        )
        db.add(revision)
        db.flush()
        artifact = DerivedArtifact(
            tenant_id=reviewer.tenant_id,
            asset_revision_id=revision.id,
            artifact_kind="transcript_segment",
            content_hash="d" * 64,
            provider="test.stt",
            provider_version="1.0",
            quality_state="review_required",
            confidence=0.61,
            content="先確認壓力歸零",
            metadata_json={},
        )
        db.add(artifact)
        db.flush()
        db.add(
            EvidenceSpan(
                tenant_id=reviewer.tenant_id,
                artifact_id=artifact.id,
                asset_revision_id=revision.id,
                locator_kind="audio",
                start_ms=402_000,
                end_ms=438_000,
            )
        )
        db.add(
            IngestionJob(
                tenant_id=reviewer.tenant_id,
                asset_revision_id=revision.id,
                adapter_key="core.long_interview_audio",
                adapter_version="1.0",
                requested_capabilities=["transcribe"],
                idempotency_key=f"review-api-{uuid4()}",
                status="review_required",
                phase="human_review",
                quality_state="review_required",
            )
        )
        db.commit()
        item_id = f"artifact:{artifact.id}"
    finally:
        db.close()

    inbox = await client.get(
        "/api/v1/knowledge/review-items", headers=superuser_headers
    )
    assert inbox.status_code == 200
    item = next(row for row in inbox.json()["items"] if row["id"] == item_id)
    assert item["evidence"][0]["start_ms"] == 402_000
    assert item["publication"]["acl"]["policy_revision"] == 1

    blocked = await client.post(
        f"/api/v1/knowledge/review-items/{item_id}/decision",
        headers=superuser_headers,
        json={"decision": "approved"},
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "low_confidence_acknowledgement_required"

    approved = await client.post(
        f"/api/v1/knowledge/review-items/{item_id}/decision",
        headers=superuser_headers,
        json={
            "decision": "approved",
            "acknowledge_low_confidence": True,
            "notes": "已核對 06:42–07:18",
        },
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["knowledge_authority"]["unit_id"]

    replay = await client.post(
        f"/api/v1/knowledge/review-items/{item_id}/decision",
        headers=superuser_headers,
        json={
            "decision": "approved",
            "acknowledge_low_confidence": True,
            "notes": "已核對 06:42–07:18",
        },
    )
    assert replay.status_code == 200
    assert replay.json()["idempotent"] is True

    db = Session()
    try:
        assert (
            db.query(KnowledgeUnitRecord)
            .filter(KnowledgeUnitRecord.unit_key == f"artifact:{artifact.id}")
            .count()
            == 1
        )
        audits = (
            db.query(AuditLog)
            .filter(
                AuditLog.action == "knowledge_review_decision",
                AuditLog.target_id == item_id,
            )
            .all()
        )
        assert len(audits) == 1
        assert audits[0].detail_json["decision"] == "approved"
        assert audits[0].detail_json["evidence_ids"]
        assert audits[0].detail_json["policy_version"] == 1
    finally:
        db.close()
