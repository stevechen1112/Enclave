"""sync_model_columns_to_schema

Revision ID: bf9bb1b20762
Revises: d1e2f3a4b5c6
Create Date: 2026-02-24 22:27:53.101178

Idempotent for fresh installs: initial schema never had documents.file_size /
legacy brand columns that this revision originally assumed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = 'bf9bb1b20762'
down_revision: Union[str, None] = 'd1e2f3a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _cols(table: str) -> set[str]:
    bind = op.get_bind()
    return {c["name"] for c in inspect(bind).get_columns(table)}


def _indexes(table: str) -> set[str]:
    bind = op.get_bind()
    return {i["name"] for i in inspect(bind).get_indexes(table) if i.get("name")}


def _tables() -> set[str]:
    bind = op.get_bind()
    return set(inspect(bind).get_table_names())


def upgrade() -> None:
    tables = _tables()

    if "customdomains" in tables:
        for name in (
            "ix_customdomains_domain",
            "ix_customdomains_id",
            "ix_customdomains_tenant_id",
        ):
            if name in _indexes("customdomains"):
                op.drop_index(op.f(name), table_name="customdomains")
        op.drop_table("customdomains")

    if "tenant_sso_configs" in tables:
        for name in (
            "ix_tenant_sso_configs_id",
            "ix_tenant_sso_configs_tenant_id",
        ):
            if name in _indexes("tenant_sso_configs"):
                op.drop_index(op.f(name), table_name="tenant_sso_configs")
        op.drop_table("tenant_sso_configs")

    chunk_cols = _cols("documentchunks")
    if "vector_id" not in chunk_cols:
        op.add_column("documentchunks", sa.Column("vector_id", sa.String(), nullable=True))
    if "ix_documentchunks_tenant_embedding" in _indexes("documentchunks"):
        op.drop_index(
            op.f("ix_documentchunks_tenant_embedding"),
            table_name="documentchunks",
            postgresql_where="(embedding IS NOT NULL)",
        )

    doc_cols = _cols("documents")
    if "file_size" not in doc_cols:
        op.add_column("documents", sa.Column("file_size", sa.Integer(), nullable=True))
    else:
        # Historical DBs may have BIGINT; normalize to Integer when present.
        op.alter_column(
            "documents",
            "file_size",
            existing_type=sa.BIGINT(),
            type_=sa.Integer(),
            existing_nullable=True,
        )

    if "quality_report" in doc_cols:
        op.alter_column(
            "documents",
            "quality_report",
            existing_type=postgresql.JSONB(astext_type=sa.Text()),
            type_=sa.JSON(),
            existing_nullable=True,
        )

    for col in ("checksum", "page_count", "mime_type", "lang"):
        if col in doc_cols:
            op.drop_column("documents", col)

    tenant_cols = _cols("tenants")
    for col in (
        "contact_name",
        "contact_phone",
        "tax_id",
        "brand_name",
        "contact_email",
        "brand_logo_url",
        "brand_primary_color",
        "custom_domain",
        "brand_favicon_url",
        "data_residency_note",
        "brand_secondary_color",
        "region",
    ):
        if col in tenant_cols:
            op.drop_column("tenants", col)


def downgrade() -> None:
    # Downgrade left as best-effort; fresh Pilot DBs should re-migrate forward.
    op.add_column("tenants", sa.Column("region", sa.VARCHAR(length=10), server_default=sa.text("'ap'::character varying"), autoincrement=False, nullable=False))
    op.add_column("tenants", sa.Column("brand_secondary_color", sa.VARCHAR(length=7), autoincrement=False, nullable=True))
    op.add_column("tenants", sa.Column("data_residency_note", sa.TEXT(), autoincrement=False, nullable=True))
    op.add_column("tenants", sa.Column("brand_favicon_url", sa.VARCHAR(length=500), autoincrement=False, nullable=True))
    op.add_column("tenants", sa.Column("custom_domain", sa.VARCHAR(length=255), autoincrement=False, nullable=True))
    op.add_column("tenants", sa.Column("brand_primary_color", sa.VARCHAR(length=7), autoincrement=False, nullable=True))
    op.add_column("tenants", sa.Column("brand_logo_url", sa.VARCHAR(length=500), autoincrement=False, nullable=True))
    op.add_column("tenants", sa.Column("contact_email", sa.VARCHAR(), autoincrement=False, nullable=True))
    op.add_column("tenants", sa.Column("brand_name", sa.VARCHAR(length=100), autoincrement=False, nullable=True))
    op.add_column("tenants", sa.Column("tax_id", sa.VARCHAR(), autoincrement=False, nullable=True))
    op.add_column("tenants", sa.Column("contact_phone", sa.VARCHAR(), autoincrement=False, nullable=True))
    op.add_column("tenants", sa.Column("contact_name", sa.VARCHAR(), autoincrement=False, nullable=True))
