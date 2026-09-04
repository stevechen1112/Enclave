"""Add media-v2 analysis lineage and entity projections.

Revision ID: av_media_v2_001
Revises: input_i10_confidence_001
"""

from __future__ import annotations

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "av_media_v2_001"
down_revision: str | None = "input_i10_confidence_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "media_analysis_runs",
    "artifact_derivation_links",
    "asset_entity_links",
    "knowledge_unit_entity_links",
    "entity_relationships",
)


def _rls(table: str) -> None:
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(
        f"""CREATE POLICY tenant_isolation ON "{table}"
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
          OR current_setting('app.bypass_rls', true) = 'on')
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
          OR current_setting('app.bypass_rls', true) = 'on')"""
    )
    if os.environ.get("RLS_ENFORCEMENT_ENABLED", "false").lower() == "true":
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_knowledge_entities_tenant_id", "knowledge_entities", ["tenant_id", "id"]
    )
    op.drop_constraint("ck_derived_artifacts_kind", "derived_artifacts", type_="check")
    kinds = (
        "extracted_text",
        "layout_page",
        "ocr_region",
        "table",
        "transcript_segment",
        "media_proxy",
        "keyframe",
        "video_scene",
        "audio_event",
        "speaker_turn",
        "action_event",
        "equipment_state",
        "timeline_alignment",
        "sop_conflict_report",
        "procedure_candidate",
        "entity_candidate",
        "media_probe",
        "audio_quality_profile",
        "audio_working_copy",
        "transcript_raw",
        "transcript_correction",
        "video_keyframe_candidate",
        "ocr_track",
        "visual_observation",
        "audio_signal_outlier",
        "multimodal_segment_summary",
    )
    op.create_check_constraint(
        "ck_derived_artifacts_kind",
        "derived_artifacts",
        "artifact_kind IN (" + ", ".join(f"'{kind}'" for kind in kinds) + ")",
    )
    json_type = postgresql.JSON(astext_type=sa.Text())
    uuid_type = postgresql.UUID(as_uuid=True)
    op.create_table(
        "media_analysis_runs",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("tenant_id", uuid_type, nullable=False),
        sa.Column("asset_revision_id", uuid_type, nullable=False),
        sa.Column("run_key", sa.String(160), nullable=False),
        sa.Column("pipeline_version", sa.String(100), nullable=False),
        sa.Column("profile", sa.String(80), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column(
            "provider_manifest",
            json_type,
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column(
            "configuration_json",
            json_type,
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column("configuration_hash", sa.String(64), nullable=False),
        sa.Column(
            "checkpoint_json",
            json_type,
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column(
            "quality_metrics",
            json_type,
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column(
            "cost_metrics",
            json_type,
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column(
            "failure_json",
            json_type,
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('queued','running','review_required','completed','degraded','failed','cancelled')",
            name="ck_media_analysis_run_status",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "asset_revision_id"],
            ["asset_revisions.tenant_id", "asset_revisions.id"],
            name="fk_media_analysis_run_revision",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_media_analysis_runs_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "asset_revision_id",
            "run_key",
            name="uq_media_analysis_run_key",
        ),
    )
    op.create_index(
        "ix_media_analysis_run_revision_status",
        "media_analysis_runs",
        ["tenant_id", "asset_revision_id", "status"],
    )
    op.create_index(
        "ix_media_analysis_runs_tenant_id", "media_analysis_runs", ["tenant_id"]
    )
    op.create_index(
        "ix_media_analysis_runs_asset_revision_id",
        "media_analysis_runs",
        ["asset_revision_id"],
    )

    op.create_table(
        "artifact_derivation_links",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("tenant_id", uuid_type, nullable=False),
        sa.Column("run_id", uuid_type, nullable=False),
        sa.Column("parent_artifact_id", uuid_type, nullable=False),
        sa.Column("child_artifact_id", uuid_type, nullable=False),
        sa.Column(
            "relation_kind",
            sa.String(40),
            nullable=False,
            server_default="derived_from",
        ),
        sa.Column(
            "metadata_json",
            json_type,
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "parent_artifact_id <> child_artifact_id",
            name="ck_artifact_derivation_not_self",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["media_analysis_runs.tenant_id", "media_analysis_runs.id"],
            name="fk_artifact_derivation_run",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "parent_artifact_id"],
            ["derived_artifacts.tenant_id", "derived_artifacts.id"],
            name="fk_artifact_derivation_parent",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "child_artifact_id"],
            ["derived_artifacts.tenant_id", "derived_artifacts.id"],
            name="fk_artifact_derivation_child",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "run_id",
            "parent_artifact_id",
            "child_artifact_id",
            "relation_kind",
            name="uq_artifact_derivation_edge",
        ),
    )
    op.create_index(
        "ix_artifact_derivation_links_tenant_id",
        "artifact_derivation_links",
        ["tenant_id"],
    )
    op.create_index(
        "ix_artifact_derivation_links_run_id", "artifact_derivation_links", ["run_id"]
    )
    op.create_index(
        "ix_artifact_derivation_links_parent_artifact_id",
        "artifact_derivation_links",
        ["parent_artifact_id"],
    )
    op.create_index(
        "ix_artifact_derivation_links_child_artifact_id",
        "artifact_derivation_links",
        ["child_artifact_id"],
    )

    def create_entity_projection(
        table: str, owner_column: str, owner_table: str, owner_unique: str, prefix: str
    ) -> None:
        op.create_table(
            table,
            sa.Column("id", uuid_type, nullable=False),
            sa.Column("tenant_id", uuid_type, nullable=False),
            sa.Column(owner_column, uuid_type, nullable=False),
            sa.Column("entity_id", uuid_type, nullable=False),
            sa.Column(
                "link_kind",
                sa.String(50),
                nullable=False,
                server_default="mentions" if prefix == "asset" else "about",
            ),
            sa.Column(
                "status", sa.String(24), nullable=False, server_default="candidate"
            ),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column(
                "evidence_json",
                json_type,
                nullable=False,
                server_default=sa.text("'[]'::json"),
            ),
            sa.Column("projector_version", sa.String(100), nullable=False),
            sa.Column("source_hash", sa.String(64), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.CheckConstraint(
                "status IN ('candidate','approved','rejected','revoked')",
                name=f"ck_{prefix}_entity_status",
            ),
            sa.CheckConstraint(
                "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
                name=f"ck_{prefix}_entity_confidence",
            ),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
            sa.ForeignKeyConstraint(
                ["tenant_id", owner_column],
                [f"{owner_table}.tenant_id", f"{owner_table}.id"],
                name=owner_unique,
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["tenant_id", "entity_id"],
                ["knowledge_entities.tenant_id", "knowledge_entities.id"],
                name=f"fk_{prefix}_entity_entity",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "tenant_id",
                owner_column,
                "entity_id",
                "link_kind",
                "projector_version",
                "source_hash",
                name=f"uq_{prefix}_entity_projection",
            ),
        )
        op.create_index(
            f"ix_{prefix}_entity_lookup", table, ["tenant_id", "entity_id", "status"]
        )
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
        op.create_index(f"ix_{table}_{owner_column}", table, [owner_column])
        op.create_index(f"ix_{table}_entity_id", table, ["entity_id"])

    create_entity_projection(
        "asset_entity_links",
        "asset_revision_id",
        "asset_revisions",
        "fk_asset_entity_revision",
        "asset",
    )
    create_entity_projection(
        "knowledge_unit_entity_links",
        "unit_revision_id",
        "knowledge_unit_revisions",
        "fk_unit_entity_revision",
        "knowledge_unit",
    )

    op.create_table(
        "entity_relationships",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("tenant_id", uuid_type, nullable=False),
        sa.Column("source_entity_id", uuid_type, nullable=False),
        sa.Column("target_entity_id", uuid_type, nullable=False),
        sa.Column("relation_kind", sa.String(80), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="candidate"),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "evidence_json",
            json_type,
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
        sa.Column("projector_version", sa.String(100), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "source_entity_id <> target_entity_id",
            name="ck_entity_relationship_not_self",
        ),
        sa.CheckConstraint(
            "status IN ('candidate','approved','rejected','revoked')",
            name="ck_entity_relationship_status",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_entity_relationship_confidence",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "source_entity_id"],
            ["knowledge_entities.tenant_id", "knowledge_entities.id"],
            name="fk_entity_relationship_source",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "target_entity_id"],
            ["knowledge_entities.tenant_id", "knowledge_entities.id"],
            name="fk_entity_relationship_target",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "source_entity_id",
            "target_entity_id",
            "relation_kind",
            "projector_version",
            "source_hash",
            name="uq_entity_relationship_projection",
        ),
    )
    op.create_index(
        "ix_entity_relationship_source",
        "entity_relationships",
        ["tenant_id", "source_entity_id", "status"],
    )
    op.create_index(
        "ix_entity_relationship_target",
        "entity_relationships",
        ["tenant_id", "target_entity_id", "status"],
    )
    op.create_index(
        "ix_entity_relationships_tenant_id", "entity_relationships", ["tenant_id"]
    )
    op.create_index(
        "ix_entity_relationships_source_entity_id",
        "entity_relationships",
        ["source_entity_id"],
    )
    op.create_index(
        "ix_entity_relationships_target_entity_id",
        "entity_relationships",
        ["target_entity_id"],
    )
    for table in TABLES:
        _rls(table)


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table)
    op.drop_constraint("ck_derived_artifacts_kind", "derived_artifacts", type_="check")
    original = (
        "extracted_text",
        "layout_page",
        "ocr_region",
        "table",
        "transcript_segment",
        "media_proxy",
        "keyframe",
        "video_scene",
        "audio_event",
        "speaker_turn",
        "action_event",
        "equipment_state",
        "timeline_alignment",
        "sop_conflict_report",
        "procedure_candidate",
        "entity_candidate",
    )
    op.create_check_constraint(
        "ck_derived_artifacts_kind",
        "derived_artifacts",
        "artifact_kind IN (" + ", ".join(f"'{kind}'" for kind in original) + ")",
    )
    op.drop_constraint(
        "uq_knowledge_entities_tenant_id", "knowledge_entities", type_="unique"
    )
