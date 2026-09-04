from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401 - load complete FK metadata
from app.db.base_class import Base
from app.models.asset import ARTIFACT_KINDS, AssetRevision, SourceAsset
from app.models.media_analysis import (
    ArtifactDerivationLink,
    AssetEntityLink,
    EntityRelationship,
    KnowledgeUnitEntityLink,
    MediaAnalysisRun,
)
from app.models.tenant import Tenant
from app.services.media_analysis_runs import (
    get_or_create_analysis_run,
    project_derivation_link,
    transition_analysis_run,
)


def test_media_v2_artifact_vocabulary_is_backward_compatible():
    assert {"transcript_segment", "keyframe", "timeline_alignment"} <= set(
        ARTIFACT_KINDS
    )
    assert {
        "audio_quality_profile",
        "audio_working_copy",
        "transcript_raw",
        "transcript_correction",
        "video_keyframe_candidate",
        "ocr_track",
        "multimodal_segment_summary",
    } <= set(ARTIFACT_KINDS)


def test_every_new_projection_has_tenant_composite_foreign_keys():
    expected = {
        MediaAnalysisRun: {"tenant_id", "asset_revision_id"},
        ArtifactDerivationLink: {
            "tenant_id",
            "run_id",
            "parent_artifact_id",
            "child_artifact_id",
        },
        AssetEntityLink: {"tenant_id", "asset_revision_id", "entity_id"},
        KnowledgeUnitEntityLink: {"tenant_id", "unit_revision_id", "entity_id"},
        EntityRelationship: {"tenant_id", "source_entity_id", "target_entity_id"},
    }
    for model, relevant_columns in expected.items():
        composite = [
            constraint
            for constraint in model.__table__.foreign_key_constraints
            if len(constraint.columns) > 1
        ]
        covered = {
            column.name for constraint in composite for column in constraint.columns
        }
        assert relevant_columns - {"tenant_id"} <= covered
        assert all(
            "tenant_id" in {column.name for column in constraint.columns}
            for constraint in composite
        )


def test_analysis_run_creation_is_idempotent(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'media.db'}")
    Base.metadata.create_all(
        engine,
        tables=[
            Tenant.__table__,
            SourceAsset.__table__,
            AssetRevision.__table__,
            MediaAnalysisRun.__table__,
        ],
    )
    tenant_id, revision_id = uuid.uuid4(), uuid.uuid4()
    with Session(engine) as db:
        db.add(Tenant(id=tenant_id, name="Tenant"))
        asset = SourceAsset(
            id=uuid.uuid4(), tenant_id=tenant_id, asset_kind="audio", title="Audio"
        )
        db.add(asset)
        db.flush()
        db.add(
            AssetRevision(
                id=revision_id,
                tenant_id=tenant_id,
                asset_id=asset.id,
                revision=1,
                media_type="audio/wav",
                content_uri="fixture.wav",
                content_hash="a" * 64,
            )
        )
        db.commit()
        first, created = get_or_create_analysis_run(
            db,
            tenant_id=tenant_id,
            asset_revision_id=revision_id,
            pipeline_version="2.0",
            profile="interview",
            configuration={"vad": True},
            provider_manifest={"stt": "test"},
        )
        assert created is True
        db.commit()
        second, created = get_or_create_analysis_run(
            db,
            tenant_id=tenant_id,
            asset_revision_id=revision_id,
            pipeline_version="2.0",
            profile="interview",
            configuration={"vad": True},
            provider_manifest={"stt": "test"},
        )
        assert created is False
        assert second.id == first.id


def test_completed_analysis_run_cannot_be_reopened():
    run = MediaAnalysisRun(status="queued")
    transition_analysis_run(run, status="running")
    transition_analysis_run(run, status="completed")
    with pytest.raises(ValueError, match="invalid"):
        transition_analysis_run(run, status="running")


def test_derivation_link_is_persisted_and_cannot_self_reference():
    class Query:
        def filter(self, *args):
            return self

        def first(self):
            return None

    class DB:
        def __init__(self):
            self.rows = []

        def query(self, *args):
            return Query()

        def add(self, row):
            self.rows.append(row)

        def flush(self):
            return None

    db = DB()
    tenant_id, run_id, parent_id, child_id = (uuid.uuid4() for _ in range(4))
    row = project_derivation_link(
        db,
        tenant_id=tenant_id,
        run_id=run_id,
        parent_artifact_id=parent_id,
        child_artifact_id=child_id,
    )
    assert row in db.rows
    with pytest.raises(ValueError, match="cannot reference itself"):
        project_derivation_link(
            db,
            tenant_id=tenant_id,
            run_id=run_id,
            parent_artifact_id=parent_id,
            child_artifact_id=parent_id,
        )


def test_migration_has_rls_and_reversible_contract():
    source = Path("app/db/migrations/versions/av_media_v2_001.py").read_text(
        encoding="utf-8"
    )
    for table in (
        "media_analysis_runs",
        "artifact_derivation_links",
        "asset_entity_links",
        "knowledge_unit_entity_links",
        "entity_relationships",
    ):
        assert table in source
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "current_setting('app.tenant_id'" in source
    assert "current_setting('app.bypass_rls'" in source
    assert "def downgrade()" in source
