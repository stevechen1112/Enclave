from __future__ import annotations

import json
from io import BytesIO
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.api.v1.endpoints.knowledge_assets import (
    _create_reference_asset,
    _create_audio_asset,
    create_asset,
    get_asset,
    list_asset_events,
    list_assets,
    retry_asset,
    tombstone_asset,
    _validate_source_url,
)
from app.models.asset import AssetRevision, DerivedArtifact, SourceAsset
from app.models.document import Document
from app.models.audit import UsageRecord
from app.models.ingestion import IngestionJob, IngestionJobEvent
from app.models.knowledge_base import KnowledgeBase
from app.models.mka import JobRole, MKATaskCost
from app.models.permission import Department
from app.models.tenant import Tenant
from app.models.user import User
from app.services.ingestion_orchestrator import get_ingestion_orchestrator
from app.services.asset_readiness import AssetReadinessState, derive_asset_lifecycle


@pytest.fixture(autouse=True)
def _isolate_asset_readiness_tables(monkeypatch):
    """These focused endpoint tests intentionally build only intake tables."""

    def fake_states(_db, *, assets, jobs_by_revision=None, **_kwargs):
        jobs_by_revision = jobs_by_revision or {}
        states = {}
        for asset in assets:
            revision = (
                _db.query(AssetRevision)
                .filter(
                    AssetRevision.asset_id == asset.id,
                    AssetRevision.revision == asset.current_revision,
                )
                .first()
            )
            job = jobs_by_revision.get(revision.id) if revision else None
            lifecycle, reasons = derive_asset_lifecycle(
                answer_ready=False,
                job_status=job.status if job else None,
                asset_status=asset.status,
                pending_review_count=0,
            )
            states[asset.id] = AssetReadinessState(
                answer_ready=False,
                lifecycle_status=lifecycle,
                pending_review_count=0,
                readiness_reasons=reasons,
            )
        return states

    monkeypatch.setattr(
        "app.services.asset_readiness.load_asset_readiness_states", fake_states
    )


def _session():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    for table in (
        Tenant.__table__,
        Department.__table__,
        JobRole.__table__,
        User.__table__,
        KnowledgeBase.__table__,
        SourceAsset.__table__,
        Document.__table__,
        AssetRevision.__table__,
        DerivedArtifact.__table__,
        UsageRecord.__table__,
        MKATaskCost.__table__,
        IngestionJob.__table__,
        IngestionJobEvent.__table__,
    ):
        table.create(engine, checkfirst=True)
    return engine, sessionmaker(bind=engine)()


def _user(db, *, role="admin"):
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
    return tenant, user


def _reference(db, user, **overrides):
    values = {
        "title": "Safety portal",
        "source_url": "https://example.invalid/safety",
        "source_system": None,
        "source_record_id": None,
        "capture_manifest": None,
        "media_type": None,
        "idempotency_key": None,
        "department_id": None,
        "data_classification": "internal",
    }
    values.update(overrides)
    return _create_reference_asset(db=db, current_user=user, **values)


def test_reference_intake_is_idempotent_visible_and_has_capability_plan():
    engine, db = _session()
    try:
        _tenant, user = _user(db)
        first = _reference(db, user, idempotency_key="web-safety-v1")
        second = _reference(db, user, idempotency_key="web-safety-v1")

        assert first["asset_kind"] == "web_page"
        assert first["job"]["adapter_key"] == "core.document"
        assert first["job"]["correlation_id"] == first["job"]["id"]
        assert first["job"]["requested_capabilities"] == ["extract_text", "layout"]
        assert second["id"] == first["id"]
        assert second["deduplicated"] is True
        assert [row["id"] for row in list_assets(db=db, current_user=user)] == [
            first["id"]
        ]
        assert (
            get_asset(UUID(first["id"]), db=db, current_user=user)["metadata"][
                "direct_intake"
            ]
            is True
        )
    finally:
        db.close()
        engine.dispose()


def test_capture_and_connector_records_use_one_contract():
    engine, db = _session()
    try:
        _tenant, user = _user(db)
        capture = _reference(
            db,
            user,
            source_url=None,
            capture_manifest=json.dumps(
                {"capture_id": "mobile-1", "title": "現場照片"}
            ),
            media_type="image/jpeg",
        )
        record = _reference(
            db,
            user,
            title="CRM record",
            source_url=None,
            source_system="crm",
            source_record_id="case-42",
        )
        assert capture["source_system"] == "capture"
        assert capture["metadata"]["capture_manifest"]["capture_id"] == "mobile-1"
        assert record["asset_kind"] == "external_record"
        assert record["source_system"] == "api:crm"
        assert record["metadata"]["upstream_source_system"] == "crm"
        assert record["job"]["adapter_key"] == "core.document"

        audio = _reference(
            db,
            user,
            source_url=None,
            capture_manifest=json.dumps({"capture_id": "interview-1"}),
            media_type="audio/wav",
        )
        assert audio["asset_kind"] == "audio"
        assert audio["job"]["adapter_key"] == "core.long_interview_audio"
        assert "transcribe" in audio["job"]["requested_capabilities"]
    finally:
        db.close()
        engine.dispose()


def test_audio_asset_detail_exposes_only_signed_proxy_url():
    engine, db = _session()
    try:
        _tenant, user = _user(db)
        created = _reference(
            db,
            user,
            source_url=None,
            capture_manifest=json.dumps({"capture_id": "audio-preview-1"}),
            media_type="audio/wav",
        )
        asset = (
            db.query(SourceAsset).filter(SourceAsset.id == UUID(created["id"])).one()
        )
        revision = (
            db.query(AssetRevision).filter(AssetRevision.asset_id == asset.id).one()
        )
        proxy = DerivedArtifact(
            tenant_id=asset.tenant_id,
            asset_revision_id=revision.id,
            artifact_kind="media_proxy",
            content_hash="f" * 64,
            provider="core.media_proxy",
            provider_version="1.0",
            quality_state="ready",
            artifact_uri="s3://private/audio.mp3",
            metadata_json={
                "storage_key": f"{asset.tenant_id}/audio.mp3",
                "media_type": "audio/mpeg",
            },
        )
        db.add(proxy)
        db.commit()

        detail = get_asset(asset.id, db=db, current_user=user)
        assert detail["preview_url"].startswith(
            f"/api/v1/media/artifacts/{proxy.id}/content?token="
        )
        assert "s3://private" not in detail["preview_url"]
    finally:
        db.close()
        engine.dispose()


def test_asset_lifecycle_retry_events_tombstone_and_tenant_isolation(monkeypatch):
    engine, db = _session()
    try:
        _tenant, user = _user(db)
        _other_tenant, outsider = _user(db)
        created = _reference(db, user)
        asset_id = UUID(created["id"])

        with pytest.raises(HTTPException) as denied:
            get_asset(asset_id, db=db, current_user=outsider)
        assert denied.value.status_code == 404

        job = (
            db.query(IngestionJob)
            .filter(IngestionJob.id == UUID(created["job"]["id"]))
            .one()
        )
        get_ingestion_orchestrator().transition(
            db, job, to_status="running", phase="fetch"
        )
        get_ingestion_orchestrator().transition(
            db,
            job,
            to_status="failed",
            phase="fetch",
            error={"code": "offline", "message": "source unavailable"},
        )
        db.commit()
        monkeypatch.setattr(
            "app.api.v1.endpoints.knowledge_assets._dispatch_retry",
            lambda *_args: None,
        )
        retried = retry_asset(asset_id, db=db, current_user=user)
        assert retried["job"]["status"] == "running"
        assert retried["job"]["attempt"] == 2
        assert [
            row["to_status"]
            for row in list_asset_events(asset_id, db=db, current_user=user)
        ] == ["queued", "running", "failed", "running"]

        assert (
            tombstone_asset(asset_id, db=db, current_user=user)["status"]
            == "tombstoned"
        )
        assert list_assets(db=db, current_user=user) == []
        with pytest.raises(HTTPException) as missing:
            get_asset(asset_id, db=db, current_user=user)
        assert missing.value.status_code == 404
    finally:
        db.close()
        engine.dispose()


def test_tombstone_asset_revokes_linked_document_projection(monkeypatch):
    engine, db = _session()
    try:
        _tenant, user = _user(db)
        created = _reference(db, user)
        asset_id = UUID(created["id"])
        document = Document(
            tenant_id=user.tenant_id,
            filename="scan.png",
            file_type="png",
            file_path="/private/scan.png",
            file_size=123,
            source_type="upload",
            status="completed",
            uploaded_by=user.id,
            source_asset_id=asset_id,
        )
        db.add(document)
        db.commit()
        calls = []

        class _Revocation:
            def revoke(self, target_db, **kwargs):
                calls.append(kwargs)
                row = (
                    target_db.query(Document)
                    .filter(Document.id == kwargs["document_id"])
                    .one()
                )
                row.status = "deleted"
                from datetime import datetime, timezone

                row.tombstoned_at = datetime.now(timezone.utc)
                target_db.commit()
                return {"ok": True}

        monkeypatch.setattr(
            "app.services.document_revocation.get_document_revocation",
            lambda: _Revocation(),
        )

        result = tombstone_asset(asset_id, db=db, current_user=user)

        assert result["status"] == "tombstoned"
        assert result["revoked_documents"] == 1
        assert calls == [
            {
                "document_id": document.id,
                "actor_id": user.id,
                "tenant_id": user.tenant_id,
                "reason": "source_asset_user_request",
            }
        ]
        assert (
            db.query(Document).filter(Document.id == document.id).one().tombstoned_at
            is not None
        )
        assert (
            db.query(SourceAsset).filter(SourceAsset.id == asset_id).one().tombstoned_at
            is not None
        )
    finally:
        db.close()
        engine.dispose()


def test_tombstone_asset_fails_closed_when_linked_document_cannot_be_revoked(
    monkeypatch,
):
    engine, db = _session()
    try:
        _tenant, user = _user(db)
        created = _reference(db, user)
        asset_id = UUID(created["id"])
        document = Document(
            tenant_id=user.tenant_id,
            filename="scan.png",
            file_type="png",
            file_path="/private/scan.png",
            file_size=123,
            source_type="upload",
            status="completed",
            uploaded_by=user.id,
            source_asset_id=asset_id,
        )
        db.add(document)
        db.commit()

        class _Revocation:
            def revoke(self, _target_db, **_kwargs):
                return {"ok": False, "reason": "tombstone_failed"}

        monkeypatch.setattr(
            "app.services.document_revocation.get_document_revocation",
            lambda: _Revocation(),
        )

        with pytest.raises(HTTPException) as exc_info:
            tombstone_asset(asset_id, db=db, current_user=user)

        assert exc_info.value.status_code == 409
        assert (
            db.query(Document).filter(Document.id == document.id).one().tombstoned_at
            is None
        )
        assert (
            db.query(SourceAsset).filter(SourceAsset.id == asset_id).one().tombstoned_at
            is None
        )
    finally:
        db.close()
        engine.dispose()


def test_reference_validation_and_write_permission_fail_closed():
    engine, db = _session()
    try:
        _tenant, admin = _user(db)
        with pytest.raises(HTTPException) as invalid_url:
            _reference(db, admin, source_url="file:///secret")
        assert invalid_url.value.status_code == 400
        with pytest.raises(HTTPException) as invalid_manifest:
            _reference(db, admin, source_url=None, capture_manifest="[]")
        assert invalid_manifest.value.status_code == 400
        for blocked in (
            "http://127.0.0.1/admin",
            "http://localhost/",
            "http://10.0.0.1/",
        ):
            with pytest.raises(HTTPException):
                _validate_source_url(blocked)

        _tenant2, viewer = _user(db, role="viewer")
        created = _reference(db, viewer)
        with pytest.raises(HTTPException) as forbidden:
            tombstone_asset(UUID(created["id"]), db=db, current_user=viewer)
        assert forbidden.value.status_code == 403
    finally:
        db.close()
        engine.dispose()


@pytest.mark.asyncio
async def test_audio_upload_persists_job_and_dispatches_worker(monkeypatch):
    engine, db = _session()
    dispatched = []

    class Storage:
        def put(self, key, path):
            assert key and path
            return f"s3://test/{key}"

        def delete(self, _key):
            return None

    try:
        _tenant, user = _user(db)
        monkeypatch.setattr(
            "app.services.file_scan.scan_file_path", lambda *_args: None
        )
        monkeypatch.setattr(
            "app.services.storage.get_storage_backend", lambda: Storage()
        )
        monkeypatch.setattr(
            "app.crud.crud_tenant.lock_and_check_storage_quota",
            lambda *_args: {"allowed": True},
        )
        monkeypatch.setattr(
            "app.services.cost_guardrails.probe_media_duration_ms",
            lambda _path: 1_000,
        )
        monkeypatch.setattr(
            "app.tasks.audio_tasks.process_audio_asset.delay",
            lambda *args: dispatched.append(args),
        )
        result = await _create_audio_asset(
            db=db,
            file=UploadFile(
                filename="interview.wav", file=BytesIO(b"RIFFtestWAVEdata")
            ),
            current_user=user,
            title="訪談",
            idempotency_key="audio-1",
            department_id=None,
            data_classification="internal",
        )
        assert result["asset_kind"] == "audio"
        assert result["job"]["adapter_key"] == "core.long_interview_audio"
        assert result["dispatched"] is True
        assert len(dispatched) == 1

        duplicate = await _create_audio_asset(
            db=db,
            file=UploadFile(
                filename="interview.wav", file=BytesIO(b"RIFFtestWAVEdata")
            ),
            current_user=user,
            title="訪談重送",
            idempotency_key="audio-2",
            department_id=None,
            data_classification="internal",
        )
        assert duplicate["id"] == result["id"]
        assert duplicate["deduplicated"] is True
        assert duplicate["dispatched"] is False
        assert db.query(SourceAsset).count() == 1
        assert db.query(AssetRevision).count() == 1
        assert len(dispatched) == 1

        differently_classified = await _create_audio_asset(
            db=db,
            file=UploadFile(
                filename="interview.wav", file=BytesIO(b"RIFFtestWAVEdata")
            ),
            current_user=user,
            title="機密訪談",
            idempotency_key="audio-3",
            department_id=None,
            data_classification="confidential",
        )
        assert differently_classified["id"] != result["id"]
        assert differently_classified["deduplicated"] is False
        assert db.query(SourceAsset).count() == 2
        assert db.query(AssetRevision).count() == 2
        assert len(dispatched) == 2
    finally:
        db.close()
        engine.dispose()


@pytest.mark.asyncio
async def test_unified_video_intake_uses_canonical_video_response_id(monkeypatch):
    engine, db = _session()
    try:
        _tenant, user = _user(db)
        existing = _reference(db, user, title="video placeholder")
        asset = (
            db.query(SourceAsset).filter(SourceAsset.id == UUID(existing["id"])).one()
        )
        asset.asset_kind = "video"
        db.commit()

        async def fake_upload_video_asset(**_kwargs):
            return {
                "id": str(asset.id),
                "deduplicated": True,
                "dispatched": False,
            }

        monkeypatch.setattr(
            "app.api.v1.endpoints.video_assets.upload_video_asset",
            fake_upload_video_asset,
        )
        result = await create_asset(
            db=db,
            current_user=user,
            file=UploadFile(filename="machine.mp4", file=BytesIO(b"video")),
            title="machine video",
            source_url=None,
            source_system=None,
            source_record_id=None,
            capture_manifest=None,
            media_type=None,
            idempotency_key=None,
            department_id=None,
            data_classification="confidential",
        )

        assert result["id"] == str(asset.id)
        assert result["asset_kind"] == "video"
        assert result["deduplicated"] is True
    finally:
        db.close()
        engine.dispose()
