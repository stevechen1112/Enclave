"""DD-M04: partial unique indexes for concurrent idempotency.

Revision ID: p1_dd_m04_unique_indexes_001
Revises: p3_parent_chunk_001
"""
from typing import Sequence, Union

from alembic import op

revision: str = "p1_dd_m04_unique_indexes_001"
down_revision: Union[str, None] = "p3_parent_chunk_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Active connector-sourced documents: one logical external record per tenant
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_documents_tenant_source_record_active
        ON documents (tenant_id, source_system, source_record_id)
        WHERE source_system IS NOT NULL
          AND source_record_id IS NOT NULL
          AND tombstoned_at IS NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_documentchunks_document_index
        ON documentchunks (document_id, chunk_index)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_documentchunks_document_hash
        ON documentchunks (document_id, chunk_hash)
        WHERE chunk_hash IS NOT NULL
        """
    )
    # PG15+: NULLS NOT DISTINCT so multiple NULL provider_instance_id cannot duplicate
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_projection_status_resource_provider
        ON projection_status (resource_type, resource_id, provider, provider_instance_id)
        NULLS NOT DISTINCT
        """
    )
    op.execute(
        """
        ALTER TABLE gateway_resources
        DROP CONSTRAINT IF EXISTS uq_gateway_resource_mapping
        """
    )
    op.execute(
        """
        DROP INDEX IF EXISTS uq_gateway_resource_mapping
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_gateway_resource_mapping_nulls
        ON gateway_resources (
            enclave_resource_type,
            enclave_resource_id,
            provider,
            provider_instance_id
        )
        NULLS NOT DISTINCT
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_gateway_resource_mapping_nulls")
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_gateway_resource_mapping
        ON gateway_resources (
            enclave_resource_type,
            enclave_resource_id,
            provider,
            provider_instance_id
        )
        """
    )
    op.execute("DROP INDEX IF EXISTS uq_projection_status_resource_provider")
    op.execute("DROP INDEX IF EXISTS uq_documentchunks_document_hash")
    op.execute("DROP INDEX IF EXISTS uq_documentchunks_document_index")
    op.execute("DROP INDEX IF EXISTS uq_documents_tenant_source_record_active")
