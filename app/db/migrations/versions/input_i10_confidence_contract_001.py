"""Replace historical video confidence sentinels with explicit unknown semantics.

Revision ID: input_i10_confidence_001
Revises: tenant_force_rls_pra_002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "input_i10_confidence_001"
down_revision: str | None = "tenant_force_rls_pra_002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enable_audited_bypass(operation: str) -> None:
    bind = op.get_bind()
    access = (
        bind.execute(
            sa.text(
                """
            SELECT
                c.relrowsecurity,
                c.relforcerowsecurity,
                r.rolsuper,
                r.rolbypassrls,
                c.relowner = r.oid AS is_table_owner,
                CASE
                    WHEN to_regrole('enclave_rls_bypass') IS NULL THEN false
                    ELSE pg_has_role(
                        current_user,
                        to_regrole('enclave_rls_bypass'),
                        'member'
                    )
                END AS is_bypass_member
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_roles r ON r.rolname = current_user
            WHERE n.nspname = 'public' AND c.relname = 'derived_artifacts'
            """
            )
        )
        .mappings()
        .one()
    )
    can_bypass_without_marker = bool(
        access["rolsuper"]
        or access["rolbypassrls"]
        or (access["is_table_owner"] and not access["relforcerowsecurity"])
    )
    is_bypass_member = bool(access["is_bypass_member"])
    if access["relrowsecurity"] and not (can_bypass_without_marker or is_bypass_member):
        raise RuntimeError(
            "migration role is not authorised for cross-tenant confidence repair"
        )
    bind.execute(
        sa.text(
            """
            INSERT INTO platform_maintenance_audit
                (actor_identity, operation, reason, correlation_id, metadata_json)
            VALUES
                ('alembic', :operation,
                 'repair known historical confidence sentinel across tenants',
                 'input_i10_confidence_contract_001', '{}'::json)
            """
        ),
        {"operation": operation},
    )
    if is_bypass_member:
        bind.execute(sa.text("SELECT set_config('app.bypass_rls', 'on', true)"))


def upgrade() -> None:
    # core.video 1.0 always persisted OpenAI's absent confidence as numeric zero.
    # Limit the repair to that known producer/version and tag repaired rows so a
    # measured zero from any other provider is never rewritten.
    _enable_audited_bypass("input_i10_confidence_contract_upgrade")
    op.execute(
        """
        UPDATE derived_artifacts
        SET confidence = NULL,
            metadata_json = (COALESCE(metadata_json::jsonb, '{}'::jsonb) ||
                jsonb_build_object(
                    'confidence_semantics', 'unknown',
                    'confidence_provider_supplied', false,
                    'confidence_calibration_version', 'unavailable',
                    'confidence_repaired_by', 'input_i10_confidence_contract_001',
                    'source_provider', COALESCE(metadata_json::jsonb->>'source_provider', 'openai'),
                    'source_provider_version', COALESCE(metadata_json::jsonb->>'source_provider_version', 'unknown_historical'),
                    'source_model', COALESCE(metadata_json::jsonb->>'source_model', 'unknown_historical')
                ))::json
        WHERE artifact_kind = 'transcript_segment'
          AND provider = 'core.video'
          AND provider_version = '1.0'
          AND confidence = 0
          AND NOT (COALESCE(metadata_json::jsonb, '{}'::jsonb) ? 'confidence_provider_supplied')
        """
    )
    # The long-interview audio worker already stored absent confidence as NULL,
    # but older rows did not explain that NULL. Backfill provenance without
    # inventing a score or rewriting a legitimate measured zero.
    op.execute(
        """
        UPDATE derived_artifacts
        SET metadata_json = (COALESCE(metadata_json::jsonb, '{}'::jsonb) ||
                jsonb_build_object(
                    'confidence_semantics', 'unknown',
                    'confidence_provider_supplied', false,
                    'confidence_calibration_version', 'unavailable',
                    'confidence_metadata_repaired_by', 'input_i10_confidence_contract_001',
                    'source_provider', COALESCE(metadata_json::jsonb->>'source_provider', 'openai'),
                    'source_provider_version', COALESCE(metadata_json::jsonb->>'source_provider_version', 'unknown_historical'),
                    'source_model', COALESCE(metadata_json::jsonb->>'source_model', 'unknown_historical')
                ))::json
        WHERE artifact_kind = 'transcript_segment'
          AND provider = 'openai'
          AND provider_version = 'long_interview_stt.i5'
          AND confidence IS NULL
          AND NOT (COALESCE(metadata_json::jsonb, '{}'::jsonb) ? 'confidence_provider_supplied')
        """
    )


def downgrade() -> None:
    _enable_audited_bypass("input_i10_confidence_contract_downgrade")
    op.execute(
        """
        UPDATE derived_artifacts
        SET confidence = 0,
            metadata_json = (COALESCE(metadata_json::jsonb, '{}'::jsonb) -
                'confidence_semantics' -
                'confidence_provider_supplied' -
                'confidence_calibration_version' -
                'confidence_repaired_by')::json
        WHERE artifact_kind = 'transcript_segment'
          AND provider = 'core.video'
          AND provider_version = '1.0'
          AND confidence IS NULL
          AND metadata_json::jsonb->>'confidence_repaired_by' =
              'input_i10_confidence_contract_001'
        """
    )
    op.execute(
        """
        UPDATE derived_artifacts
        SET metadata_json = (COALESCE(metadata_json::jsonb, '{}'::jsonb) -
                'confidence_semantics' -
                'confidence_provider_supplied' -
                'confidence_calibration_version' -
                'confidence_metadata_repaired_by')::json
        WHERE artifact_kind = 'transcript_segment'
          AND provider = 'openai'
          AND provider_version = 'long_interview_stt.i5'
          AND confidence IS NULL
          AND metadata_json::jsonb->>'confidence_metadata_repaired_by' =
              'input_i10_confidence_contract_001'
        """
    )
