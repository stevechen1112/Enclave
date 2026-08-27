"""Extend artifact kinds for evidence-grounded multi-modal timelines.

Revision ID: multimodal_timeline_f2_010
Revises: video_artifact_review_f1_009
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "multimodal_timeline_f2_010"
down_revision: str | None = "video_artifact_review_f1_009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_F1 = (
    "'extracted_text', 'layout_page', 'ocr_region', 'table', "
    "'transcript_segment', 'keyframe', 'video_scene', 'audio_event', "
    "'procedure_candidate', 'entity_candidate'"
)
_F2 = (
    "'extracted_text', 'layout_page', 'ocr_region', 'table', "
    "'transcript_segment', 'keyframe', 'video_scene', 'audio_event', "
    "'speaker_turn', 'action_event', 'equipment_state', 'timeline_alignment', "
    "'procedure_candidate', 'entity_candidate'"
)


def _replace_constraint(values: str) -> None:
    op.drop_constraint("ck_derived_artifacts_kind", "derived_artifacts", type_="check")
    op.create_check_constraint(
        "ck_derived_artifacts_kind",
        "derived_artifacts",
        f"artifact_kind IN ({values})",
    )


def upgrade() -> None:
    _replace_constraint(_F2)


def downgrade() -> None:
    _replace_constraint(_F1)
