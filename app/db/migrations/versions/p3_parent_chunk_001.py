"""Parent chunk hierarchy for parent-child retrieval."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "p3_parent_chunk_001"
down_revision: Union[str, None] = "p2_full_plan_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "documentchunks",
        sa.Column("parent_chunk_id", UUID(as_uuid=True), sa.ForeignKey("documentchunks.id"), nullable=True),
    )
    op.create_index("ix_documentchunks_parent", "documentchunks", ["parent_chunk_id"])


def downgrade() -> None:
    op.drop_index("ix_documentchunks_parent", table_name="documentchunks")
    op.drop_column("documentchunks", "parent_chunk_id")
