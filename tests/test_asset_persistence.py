from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 - register all FK targets
from app.models.asset import AssetRevision, DerivedArtifact, EvidenceSpan, SourceAsset
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase
from app.models.mka import JobRole, KnowledgeCaptureSession
from app.models.permission import Department
from app.models.tenant import Tenant
from app.models.user import User
from app.services.asset_projection import (
    AssetProjectionConflict,
    backfill_document_assets,
    finalize_capture_asset_revision,
    document_quality_state,
    project_capture_transcript_segments,
    project_document,
    project_document_text_artifact,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def asset_db():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    tables = [
        Tenant.__table__,
        Department.__table__,
        JobRole.__table__,
        User.__table__,
        SourceAsset.__table__,
        AssetRevision.__table__,
        DerivedArtifact.__table__,
        EvidenceSpan.__table__,
        KnowledgeBase.__table__,
        Document.__table__,
    ]
    for table in tables:
        table.create(engine, checkfirst=True)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _tenant_and_user(db):
    tenant = Tenant(name=f"tenant-{uuid4().hex[:6]}")
    db.add(tenant)
    db.flush()
    user = User(
        tenant_id=tenant.id,
        email=f"{uuid4().hex}@example.test",
        hashed_password="test",
    )
    db.add(user)
    db.flush()
    return tenant, user


def test_document_projection_is_idempotent_and_revision_is_immutable(asset_db):
    tenant, user = _tenant_and_user(asset_db)
    document = Document(
        tenant_id=tenant.id,
        uploaded_by=user.id,
        filename="manual.pdf",
        file_type="pdf",
        file_path="s3://bucket/tenant/manual.pdf",
        content_hash="a" * 64,
        file_size=100,
        version=1,
        status="processing",
    )
    asset_db.add(document)
    asset_db.flush()

    first = project_document(asset_db, document)
    second = project_document(asset_db, document)

    assert first.asset_created and first.revision_created
    assert not second.asset_created and not second.revision_created
    assert document.source_asset_id == first.asset.id
    assert first.revision.content_hash == "a" * 64
    assert first.asset.current_revision == 1

    document.content_hash = "b" * 64
    with pytest.raises(AssetProjectionConflict, match="immutable"):
        project_document(asset_db, document)


def test_document_projection_creates_superseding_revision(asset_db):
    tenant, user = _tenant_and_user(asset_db)
    document = Document(
        tenant_id=tenant.id,
        uploaded_by=user.id,
        filename="manual.pdf",
        file_type="pdf",
        file_path="s3://bucket/tenant/manual-v1.pdf",
        content_hash="a" * 64,
        version=1,
        status="completed",
    )
    asset_db.add(document)
    asset_db.flush()
    first = project_document(asset_db, document, ingestion_status="ready")

    document.version = 2
    document.file_path = "s3://bucket/tenant/manual-v2.pdf"
    document.content_hash = "b" * 64
    second = project_document(asset_db, document, ingestion_status="ready")

    assert second.revision.revision == 2
    assert second.revision.supersedes_revision_id == first.revision.id
    assert second.asset.current_revision == 2


@pytest.mark.parametrize(
    ("file_type", "asset_kind", "chunk", "locator_kind", "coordinate"),
    [
        ("pdf", "document", {"text": "marker", "page": 2}, "document", ("page", 2)),
        (
            "docx",
            "document",
            {"text": "marker", "section": "停機確認", "paragraph_index": 3},
            "document",
            ("paragraph_index", 3),
        ),
        (
            "pptx",
            "document",
            {"text": "marker", "page": 2, "slide_number": 2},
            "document",
            ("slide_number", 2),
        ),
        (
            "xlsx",
            "spreadsheet",
            {"text": "marker", "worksheet": "檢驗", "cell_range": "B4:F9"},
            "table",
            ("cell_range", "B4:F9"),
        ),
        (
            "image",
            "image",
            {
                "text": "marker",
                "bbox": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0},
                "locator_fallback": True,
            },
            "image",
            ("bbox", [0.0, 0.0, 1.0, 1.0]),
        ),
    ],
)
def test_document_parse_projection_creates_typed_evidence(
    asset_db, file_type, asset_kind, chunk, locator_kind, coordinate
):
    tenant, user = _tenant_and_user(asset_db)
    document = Document(
        tenant_id=tenant.id,
        uploaded_by=user.id,
        filename=f"source.{file_type}",
        file_type=file_type,
        file_path=f"s3://bucket/source.{file_type}",
        content_hash="c" * 64,
        version=1,
        status="processing",
    )
    asset_db.add(document)
    asset_db.flush()

    artifact = project_document_text_artifact(
        asset_db,
        document=document,
        content="marker",
        provider="native",
        provider_version="1",
        metadata={
            "parse_artifact": {
                "confidence": 0.9,
                "chunks": [{"chunk_index": 0, **chunk}],
            }
        },
    )

    projected = (
        asset_db.query(DerivedArtifact).filter(DerivedArtifact.id != artifact.id).one()
    )
    evidence = asset_db.query(EvidenceSpan).one()
    assert asset_db.get(SourceAsset, document.source_asset_id).asset_kind == asset_kind
    assert projected.quality_state == (
        "review_required" if file_type == "image" else "ready"
    )
    assert artifact.metadata_json["confidence_semantics"] == (
        "internal_parse_quality_heuristic"
    )
    assert artifact.metadata_json["confidence_provider_supplied"] is False
    assert projected.metadata_json["confidence_calibration_version"] == (
        "parse-quality-heuristic.v1"
    )
    assert evidence.locator_kind == locator_kind
    assert getattr(evidence, coordinate[0]) == coordinate[1]
    if file_type == "image":
        assert evidence.locator_fallback is True


def test_document_quality_policy_requires_review_for_low_ocr_confidence():
    assert document_quality_state({"quality_score": 0.8}) == "ready"
    assert document_quality_state({"quality_score": 0.49}) == "review_required"
    assert (
        document_quality_state(
            {"quality_score": 0.8, "ocr_used": True, "ocr_confidence": 0.69}
        )
        == "review_required"
    )


def test_document_projection_preserves_provider_supplied_confidence_semantics(
    asset_db,
):
    tenant, user = _tenant_and_user(asset_db)
    document = Document(
        tenant_id=tenant.id,
        uploaded_by=user.id,
        filename="provided.pdf",
        file_type="pdf",
        file_path="s3://bucket/provided.pdf",
        content_hash="d" * 64,
        version=1,
        status="processing",
    )
    asset_db.add(document)
    asset_db.flush()

    artifact = project_document_text_artifact(
        asset_db,
        document=document,
        content="供應商文字",
        provider="ragflow",
        provider_version="2",
        metadata={
            "parse_artifact": {
                "confidence": 0.0,
                "confidence_provider_supplied": True,
                "confidence_calibration_version": "provider-native-uncalibrated",
            }
        },
    )

    assert artifact.confidence == 0.0
    assert artifact.metadata_json["confidence_semantics"] == "provider_supplied"
    assert artifact.metadata_json["confidence_provider_supplied"] is True


def test_composite_foreign_key_rejects_cross_tenant_revision(asset_db):
    tenant_a, _ = _tenant_and_user(asset_db)
    tenant_b, _ = _tenant_and_user(asset_db)
    asset = SourceAsset(
        tenant_id=tenant_a.id,
        asset_kind="document",
        title="A",
        source_system="upload",
    )
    asset_db.add(asset)
    asset_db.flush()
    asset_db.add(
        AssetRevision(
            tenant_id=tenant_b.id,
            asset_id=asset.id,
            revision=1,
            media_type="text/plain",
            content_uri="s3://bucket/a.txt",
            content_hash="a" * 64,
        )
    )

    with pytest.raises(IntegrityError):
        asset_db.flush()


def test_supersedes_cannot_point_to_another_asset(asset_db):
    tenant, _ = _tenant_and_user(asset_db)
    first_asset = SourceAsset(
        tenant_id=tenant.id,
        asset_kind="document",
        title="A",
        source_system="upload",
    )
    second_asset = SourceAsset(
        tenant_id=tenant.id,
        asset_kind="document",
        title="B",
        source_system="upload",
    )
    asset_db.add_all([first_asset, second_asset])
    asset_db.flush()
    first_revision = AssetRevision(
        tenant_id=tenant.id,
        asset_id=first_asset.id,
        revision=1,
        media_type="text/plain",
        content_uri="s3://bucket/a.txt",
        content_hash="a" * 64,
    )
    asset_db.add(first_revision)
    asset_db.flush()
    asset_db.add(
        AssetRevision(
            tenant_id=tenant.id,
            asset_id=second_asset.id,
            revision=1,
            media_type="text/plain",
            content_uri="s3://bucket/b.txt",
            content_hash="b" * 64,
            supersedes_revision_id=first_revision.id,
        )
    )

    with pytest.raises(IntegrityError):
        asset_db.flush()


def test_capture_manifest_and_transcript_have_exact_evidence(asset_db):
    tenant, user = _tenant_and_user(asset_db)
    capture = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant.id,
        owner_id=user.id,
        title="Pump interview",
        equipment_id="P-01",
        consent_version="v1",
        audio_policy_snapshot={"save_audio": True},
        total_duration_ms=2_000,
        source_asset_id=None,
        source_asset_revision_id=None,
    )
    chunks = [
        SimpleNamespace(
            sequence=0,
            offset_ms=0,
            duration_ms=1_000,
            storage_key=f"{tenant.id}/{uuid4()}.webm",
            mime_type="audio/webm",
            size_bytes=10,
            sha256="a" * 64,
        ),
        SimpleNamespace(
            sequence=1,
            offset_ms=1_000,
            duration_ms=1_000,
            storage_key=f"{tenant.id}/{uuid4()}.webm",
            mime_type="audio/webm",
            size_bytes=20,
            sha256="b" * 64,
        ),
    ]
    revision = finalize_capture_asset_revision(asset_db, capture=capture, chunks=chunks)
    segment = SimpleNamespace(
        id=uuid4(),
        sequence=0,
        start_ms=250,
        end_ms=900,
        speaker=None,
        raw_text="先確認壓力歸零。",
        corrected_text=None,
    )
    artifacts = project_capture_transcript_segments(
        asset_db,
        capture=capture,
        segments=[segment],
        provider="test-stt",
        provider_version="1.0",
    )

    evidence = asset_db.query(EvidenceSpan).one()
    assert revision.metadata_json["chunk_count"] == 2
    assert capture.source_asset_revision_id == revision.id
    assert artifacts[0].quality_state == "review_required"
    assert evidence.asset_revision_id == revision.id
    assert (evidence.start_ms, evidence.end_ms) == (250, 900)


def test_backfill_keeps_missing_bytes_as_pending_asset(asset_db):
    tenant, _ = _tenant_and_user(asset_db)
    document = Document(
        tenant_id=tenant.id,
        filename="legacy.txt",
        file_type="txt",
        status="pending",
    )
    asset_db.add(document)
    asset_db.flush()

    result = backfill_document_assets(asset_db, tenant_id=tenant.id)

    assert result == {
        "documents_scanned": 1,
        "assets_created": 1,
        "revisions_created": 0,
        "pending_source_bytes": 1,
    }
    assert document.source_asset_id is not None


def test_phase_b_migration_is_head_linked_reversible_and_rls_protected():
    migration = (
        ROOT / "app" / "db" / "migrations" / "versions" / "asset_identity_b1_007.py"
    ).read_text(encoding="utf-8")

    assert 'down_revision: str | None = "demo_tenant_boundary_k6_006"' in migration
    for table in (
        "source_assets",
        "asset_revisions",
        "derived_artifacts",
        "evidence_spans",
    ):
        assert f'"{table}"' in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "WITH CHECK" in migration
    assert "fk_asset_revisions_tenant_asset" in migration
    assert "fk_evidence_spans_artifact_revision" in migration
    assert 'op.drop_table("source_assets")' in migration


def test_phase_b_migration_upgrade_and_downgrade_render_offline():
    from app.db.migrations.versions import asset_identity_b1_007 as migration

    upgrade_buffer = StringIO()
    upgrade_context = MigrationContext.configure(
        url="postgresql://",
        opts={"as_sql": True, "output_buffer": upgrade_buffer},
    )
    with Operations.context(upgrade_context):
        migration.upgrade()

    downgrade_buffer = StringIO()
    downgrade_context = MigrationContext.configure(
        url="postgresql://",
        opts={"as_sql": True, "output_buffer": downgrade_buffer},
    )
    with Operations.context(downgrade_context):
        migration.downgrade()

    upgrade_sql = upgrade_buffer.getvalue()
    downgrade_sql = downgrade_buffer.getvalue()
    assert "CREATE TABLE source_assets" in upgrade_sql
    assert "CREATE TABLE evidence_spans" in upgrade_sql
    assert "ENABLE ROW LEVEL SECURITY" in upgrade_sql
    assert "DROP TABLE source_assets" in downgrade_sql


def test_capture_revision_fk_includes_source_asset_identity():
    constraint = next(
        item
        for item in KnowledgeCaptureSession.__table__.foreign_key_constraints
        if item.name == "fk_mka_capture_tenant_asset_revision"
    )

    assert tuple(constraint.column_keys) == (
        "tenant_id",
        "source_asset_id",
        "source_asset_revision_id",
    )
    assert tuple(element.target_fullname for element in constraint.elements) == (
        "asset_revisions.tenant_id",
        "asset_revisions.asset_id",
        "asset_revisions.id",
    )
