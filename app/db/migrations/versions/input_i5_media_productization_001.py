"""Add browser-safe media proxy artifacts for Input I5.

Revision ID: input_i5_media_product_001
Revises: input_i4_evidence_precision_001
"""

from collections.abc import Sequence

from alembic import op

revision: str = "input_i5_media_product_001"
down_revision: str | None = "input_i4_evidence_precision_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_I4 = (
    "'extracted_text', 'layout_page', 'ocr_region', 'table', "
    "'transcript_segment', 'keyframe', 'video_scene', 'audio_event', "
    "'speaker_turn', 'action_event', 'equipment_state', 'timeline_alignment', "
    "'sop_conflict_report', 'procedure_candidate', 'entity_candidate'"
)
_I5 = (
    "'extracted_text', 'layout_page', 'ocr_region', 'table', "
    "'transcript_segment', 'media_proxy', 'keyframe', 'video_scene', "
    "'audio_event', 'speaker_turn', 'action_event', 'equipment_state', "
    "'timeline_alignment', 'sop_conflict_report', 'procedure_candidate', "
    "'entity_candidate'"
)


def _replace_constraint(values: str) -> None:
    op.drop_constraint("ck_derived_artifacts_kind", "derived_artifacts", type_="check")
    op.create_check_constraint(
        "ck_derived_artifacts_kind",
        "derived_artifacts",
        f"artifact_kind IN ({values})",
    )


def upgrade() -> None:
    _replace_constraint(_I5)


def downgrade() -> None:
    _replace_constraint(_I4)
