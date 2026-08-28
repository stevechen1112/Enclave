"""Add tenant monthly cost guardrail.

Revision ID: p5_cost_guardrails_001
Revises: p2_tenant_hard_isolation_001
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "p5_cost_guardrails_001"
down_revision: str | None = "p2_tenant_hard_isolation_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns() -> set[str]:
    return {
        column["name"]
        for column in inspect(op.get_bind()).get_columns("tenants")
    }


def _checks() -> set[str]:
    return {
        constraint["name"]
        for constraint in inspect(op.get_bind()).get_check_constraints("tenants")
        if constraint.get("name")
    }


def upgrade() -> None:
    if "monthly_cost_limit_usd" not in _columns():
        op.add_column(
            "tenants",
            sa.Column("monthly_cost_limit_usd", sa.Float(), nullable=True),
        )
    op.execute(
        sa.text(
            """
            UPDATE tenants
            SET monthly_cost_limit_usd = CASE plan
                WHEN 'pilot' THEN 50.0
                WHEN 'team' THEN 500.0
                WHEN 'business' THEN 5000.0
                WHEN 'free' THEN 10.0
                WHEN 'pro' THEN 200.0
                ELSE NULL
            END
            WHERE monthly_cost_limit_usd IS NULL
              AND plan IN ('pilot', 'team', 'business', 'free', 'pro')
            """
        )
    )
    if "ck_tenants_monthly_cost_limit_nonnegative" not in _checks():
        op.create_check_constraint(
            "ck_tenants_monthly_cost_limit_nonnegative",
            "tenants",
            "monthly_cost_limit_usd IS NULL OR monthly_cost_limit_usd >= 0",
        )


def downgrade() -> None:
    if "monthly_cost_limit_usd" in _columns():
        if "ck_tenants_monthly_cost_limit_nonnegative" in _checks():
            op.drop_constraint(
                "ck_tenants_monthly_cost_limit_nonnegative",
                "tenants",
                type_="check",
            )
        op.drop_column("tenants", "monthly_cost_limit_usd")
