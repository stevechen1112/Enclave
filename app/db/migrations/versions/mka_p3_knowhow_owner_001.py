"""MKA know-how ownership: knowhow_cards.owner_id。

補上知識卡建立者欄位，供 PATCH／submit 端點做擁有者授權檢查。
既有資料 owner_id 為 NULL，由 API 層 fail-closed（僅管理員可修改無主卡片）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "mka_p3_knowhow_owner_001"
down_revision: Union[str, None] = "mka_p2_vision_platform_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "knowhow_cards",
        sa.Column("owner_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
    )
    op.create_index("ix_knowhow_cards_owner_id", "knowhow_cards", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_knowhow_cards_owner_id", table_name="knowhow_cards")
    op.drop_column("knowhow_cards", "owner_id")
