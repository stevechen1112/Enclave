"""add_tenant_security_config_fields

Revision ID: 389e29b29360
Revises: bf9bb1b20762
Create Date: 2026-02-24 22:57:30.539093

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '389e29b29360'
down_revision: Union[str, None] = 'bf9bb1b20762'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('tenants', sa.Column('isolation_level', sa.String(), server_default='standard', nullable=True))
    op.add_column('tenants', sa.Column('require_mfa', sa.Boolean(), server_default='false', nullable=True))
    op.add_column('tenants', sa.Column('ip_whitelist', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('tenants', 'ip_whitelist')
    op.drop_column('tenants', 'require_mfa')
    op.drop_column('tenants', 'isolation_level')
