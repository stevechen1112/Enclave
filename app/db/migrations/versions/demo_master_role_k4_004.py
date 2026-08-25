"""Add the master role and correct the supervised demo persona assignment.

Revision ID: demo_master_role_k4_004
Revises: schema_norm_k3_003
"""
from collections.abc import Sequence

from alembic import op

revision: str = "demo_master_role_k4_004"
down_revision: str | None = "schema_norm_k3_003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO mka_job_roles (
          id, tenant_id, role_key, name, description,
          department_ids, default_module_keys, active, created_at
        )
        SELECT
          gen_random_uuid(), t.id, 'master', '班長／師傅',
          '現場經驗、異常協助與新人傳承', '[]'::json,
          '["training_knowhow", "incident_handover", "spec_sop"]'::json,
          TRUE, now()
        FROM tenants AS t
        ON CONFLICT (tenant_id, role_key) DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE mka_user_job_role_assignments AS a
        SET active = FALSE, is_primary = FALSE, updated_at = now()
        FROM users AS u, mka_job_roles AS r
        WHERE u.email = 'master@demo.mka'
          AND a.user_id = u.id
          AND a.tenant_id = u.tenant_id
          AND r.id = a.job_role_id
          AND r.role_key <> 'master'
        """
    )
    op.execute(
        """
        INSERT INTO mka_user_job_role_assignments (
          id, tenant_id, user_id, job_role_id, is_primary, active, created_at
        )
        SELECT gen_random_uuid(), u.tenant_id, u.id, r.id, TRUE, TRUE, now()
        FROM users AS u
        JOIN mka_job_roles AS r
          ON r.tenant_id = u.tenant_id AND r.role_key = 'master'
        WHERE u.email = 'master@demo.mka'
        ON CONFLICT (tenant_id, user_id, job_role_id)
        DO UPDATE SET is_primary = TRUE, active = TRUE, updated_at = now()
        """
    )
    op.execute(
        """
        UPDATE users AS u
        SET active_job_role_id = r.id
        FROM mka_job_roles AS r
        WHERE u.email = 'master@demo.mka'
          AND r.tenant_id = u.tenant_id
          AND r.role_key = 'master'
        """
    )


def downgrade() -> None:
    # Forward-only data correction. Removing a role could invalidate tenant
    # configuration or historical TaskRun references, so downgrade is a no-op.
    pass
