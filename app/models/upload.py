"""Tenant-scoped, resumable source upload state.

The rows describe transport state only.  A committed upload is always handed
to the canonical knowledge-asset intake so transport never becomes a second
asset authority.
"""
from __future__ import annotations

import uuid

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from app.db.base_class import Base


class UploadSession(Base):
    __tablename__ = "upload_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    idempotency_key = Column(String(500), nullable=False)
    filename = Column(String(500), nullable=False)
    media_type = Column(String(255), nullable=False)
    byte_size = Column(BigInteger, nullable=False)
    part_size = Column(Integer, nullable=False)
    total_parts = Column(Integer, nullable=False)
    received_bytes = Column(BigInteger, nullable=False, default=0)
    received_parts = Column(Integer, nullable=False, default=0)
    status = Column(String(32), nullable=False, default="initialized", index=True)
    title = Column(String(500), nullable=True)
    department_id = Column(UUID(as_uuid=True), ForeignKey("departments.id"), nullable=True)
    data_classification = Column(String(50), nullable=False, default="internal")
    context_metadata = Column(JSON, nullable=False, default=dict)
    expected_sha256 = Column(String(64), nullable=True)
    content_sha256 = Column(String(64), nullable=True)
    staging_key = Column(String(128), nullable=False)
    provider_upload_id = Column(String(1000), nullable=False)
    staging_completed = Column(Integer, nullable=False, default=0)
    asset_id = Column(UUID(as_uuid=True), nullable=True)
    error_json = Column(JSON, nullable=False, default=dict)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    committed_at = Column(DateTime(timezone=True), nullable=True)
    aborted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_upload_sessions_tenant_id"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_upload_sessions_idempotency"),
        ForeignKeyConstraint(
            ["tenant_id", "asset_id"],
            ["source_assets.tenant_id", "source_assets.id"],
            name="fk_upload_sessions_tenant_asset",
        ),
        CheckConstraint("byte_size > 0", name="ck_upload_sessions_byte_size"),
        CheckConstraint("part_size > 0", name="ck_upload_sessions_part_size"),
        CheckConstraint("total_parts > 0", name="ck_upload_sessions_total_parts"),
        CheckConstraint("received_bytes >= 0", name="ck_upload_sessions_received_bytes"),
        CheckConstraint("received_parts >= 0", name="ck_upload_sessions_received_parts"),
        CheckConstraint(
            "status IN ('initialized','uploading','committing','committed','aborted','expired','failed')",
            name="ck_upload_sessions_status",
        ),
        Index("ix_upload_sessions_tenant_owner_status", "tenant_id", "owner_id", "status"),
        Index("ix_upload_sessions_status_expires", "status", "expires_at"),
    )


class UploadPart(Base):
    __tablename__ = "upload_parts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    session_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    part_number = Column(Integer, nullable=False)
    byte_size = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False)
    provider_etag = Column(String(1000), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_upload_parts_tenant_id"),
        UniqueConstraint("tenant_id", "session_id", "part_number", name="uq_upload_parts_session_number"),
        ForeignKeyConstraint(
            ["tenant_id", "session_id"],
            ["upload_sessions.tenant_id", "upload_sessions.id"],
            name="fk_upload_parts_tenant_session",
            ondelete="CASCADE",
        ),
        CheckConstraint("part_number >= 1", name="ck_upload_parts_number"),
        CheckConstraint("byte_size > 0", name="ck_upload_parts_size"),
        CheckConstraint("length(sha256) = 64", name="ck_upload_parts_sha256"),
    )
