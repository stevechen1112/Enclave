"""Add paragraph, slide and fallback precision to evidence locators."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "input_i4_evidence_precision_001"
down_revision: str | None = "input_i3_capture_policy_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("evidence_spans", sa.Column("paragraph_index", sa.Integer()))
    op.add_column("evidence_spans", sa.Column("slide_number", sa.Integer()))
    op.add_column(
        "evidence_spans",
        sa.Column(
            "locator_fallback",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_check_constraint(
        "ck_evidence_spans_paragraph",
        "evidence_spans",
        "paragraph_index IS NULL OR paragraph_index >= 1",
    )
    op.create_check_constraint(
        "ck_evidence_spans_slide",
        "evidence_spans",
        "slide_number IS NULL OR slide_number >= 1",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_evidence_spans_slide", "evidence_spans", type_="check"
    )
    op.drop_constraint(
        "ck_evidence_spans_paragraph", "evidence_spans", type_="check"
    )
    op.drop_column("evidence_spans", "locator_fallback")
    op.drop_column("evidence_spans", "slide_number")
    op.drop_column("evidence_spans", "paragraph_index")
