"""Add governed SOP conflict review output for video procedures.

Revision ID: video_governance_f3_011
Revises: multimodal_timeline_f2_010
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "video_governance_f3_011"
down_revision: str | None = "multimodal_timeline_f2_010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_F2 = (
    "'extracted_text', 'layout_page', 'ocr_region', 'table', "
    "'transcript_segment', 'keyframe', 'video_scene', 'audio_event', "
    "'speaker_turn', 'action_event', 'equipment_state', 'timeline_alignment', "
    "'procedure_candidate', 'entity_candidate'"
)
_F3 = (
    "'extracted_text', 'layout_page', 'ocr_region', 'table', "
    "'transcript_segment', 'keyframe', 'video_scene', 'audio_event', "
    "'speaker_turn', 'action_event', 'equipment_state', 'timeline_alignment', "
    "'sop_conflict_report', 'procedure_candidate', 'entity_candidate'"
)


def _replace_constraint(values: str) -> None:
    op.drop_constraint("ck_derived_artifacts_kind", "derived_artifacts", type_="check")
    op.create_check_constraint(
        "ck_derived_artifacts_kind",
        "derived_artifacts",
        f"artifact_kind IN ({values})",
    )


def upgrade() -> None:
    op.add_column(
        "artifact_review_decisions",
        sa.Column(
            "resolution_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
    )
    _replace_constraint(_F3)


def downgrade() -> None:
    _replace_constraint(_F2)
    op.drop_column("artifact_review_decisions", "resolution_json")
