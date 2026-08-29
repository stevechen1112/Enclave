"""Add tenant-scoped core capture duration policy."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "input_i3_capture_policy_001"
down_revision: str | None = "input_i2_resumable_upload_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mka_audio_policies",
        sa.Column(
            "capture_max_duration_seconds",
            sa.Integer(),
            nullable=False,
            server_default="3600",
        ),
    )
    op.create_check_constraint(
        "ck_capture_policy_max_duration",
        "mka_audio_policies",
        "capture_max_duration_seconds BETWEEN 60 AND 86400",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_capture_policy_max_duration",
        "mka_audio_policies",
        type_="check",
    )
    op.drop_column("mka_audio_policies", "capture_max_duration_seconds")
