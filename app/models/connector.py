"""Phase 3 — PipesHub Connector & Source ACL models."""
import uuid
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, ForeignKeyConstraint, func, Text, Boolean, JSON, Index, UniqueConstraint, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base_class import Base


class ConnectorInstance(Base):
    __tablename__ = "connector_instances"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    connector_type = Column(String, nullable=False)  # nas_smb | sharepoint | google_drive | ...
    name = Column(String, nullable=False)
    status = Column(String, default="active")  # active | paused | error | deleted
    config_json = Column(JSON, default=dict)
    credential_ref = Column(String, nullable=True)
    last_sync_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)
    sync_state = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    tenant = relationship("Tenant")
    resources = relationship("ConnectorResource", back_populates="connector")


class ExternalPrincipal(Base):
    __tablename__ = "external_principals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    provider = Column(String, nullable=False)
    external_id = Column(String, nullable=False)
    principal_type = Column(String, nullable=False)  # user | group | domain | public
    mapped_subject_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    mapped_subject_type = Column(String, nullable=True)  # user | department | group
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "provider", "external_id", name="uq_external_principal"),
    )


class SourceAclEntry(Base):
    __tablename__ = "source_acl_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    source_record_id = Column(String, nullable=False, index=True)
    principal_id = Column(UUID(as_uuid=True), ForeignKey("external_principals.id"), nullable=False)
    permission = Column(String, nullable=False)  # read | write | admin
    effect = Column(String, default="allow")  # allow | deny
    inherited = Column(Boolean, default=False)
    revision = Column(Integer, default=1)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    principal = relationship("ExternalPrincipal")

    __table_args__ = (
        Index("ix_source_acl_record", "tenant_id", "source_record_id"),
    )


class ConnectorResource(Base):
    __tablename__ = "connector_resources"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    connector_instance_id = Column(UUID(as_uuid=True), ForeignKey("connector_instances.id"), nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    source_record_id = Column(String, nullable=False, index=True)
    parent_source_id = Column(String, nullable=True)
    source_version = Column(String, nullable=True)
    content_hash = Column(String, nullable=True)
    acl_hash = Column(String, nullable=True)
    sync_state = Column(String, default="synced")  # pending | synced | deleted | error
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=True)
    metadata_json = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    connector = relationship("ConnectorInstance", back_populates="resources")

    __table_args__ = (
        UniqueConstraint("connector_instance_id", "source_record_id", name="uq_connector_resource"),
    )


class ImportBatch(Base):
    """A replayable folder/connector manifest with per-file outcomes."""

    __tablename__ = "import_batches"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    connector_instance_id = Column(
        UUID(as_uuid=True), ForeignKey("connector_instances.id"), nullable=True, index=True
    )
    status = Column(String(32), nullable=False, default="pending")
    root_label = Column(String(500), nullable=True)
    shared_metadata = Column(JSON, nullable=False, default=dict)
    total_items = Column(Integer, nullable=False, default=0)
    succeeded_items = Column(Integer, nullable=False, default=0)
    failed_items = Column(Integer, nullable=False, default=0)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_import_batches_tenant_id"),
        CheckConstraint(
            "status IN ('pending', 'running', 'partial', 'completed', 'failed')",
            name="ck_import_batches_status",
        ),
        Index("ix_import_batches_tenant_created", "tenant_id", "created_at"),
    )


class ImportBatchItem(Base):
    __tablename__ = "import_batch_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    batch_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    source_record_id = Column(String(500), nullable=False)
    parent_source_id = Column(String(500), nullable=True)
    status = Column(String(32), nullable=False, default="pending")
    attempts = Column(Integer, nullable=False, default=0)
    content_hash = Column(String(71), nullable=True)
    asset_id = Column(UUID(as_uuid=True), nullable=True)
    revision_id = Column(UUID(as_uuid=True), nullable=True)
    resource_json = Column(JSON, nullable=False, default=dict)
    error_code = Column(String(100), nullable=True)
    error_detail = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "batch_id"],
            ["import_batches.tenant_id", "import_batches.id"],
            name="fk_import_batch_items_tenant_batch",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "asset_id"],
            ["source_assets.tenant_id", "source_assets.id"],
            name="fk_import_batch_items_tenant_asset",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "asset_id", "revision_id"],
            ["asset_revisions.tenant_id", "asset_revisions.asset_id", "asset_revisions.id"],
            name="fk_import_batch_items_tenant_revision",
        ),
        UniqueConstraint("batch_id", "source_record_id", name="uq_import_batch_item_source"),
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed', 'skipped')",
            name="ck_import_batch_items_status",
        ),
        CheckConstraint("attempts >= 0", name="ck_import_batch_items_attempts"),
        Index("ix_import_batch_items_tenant_status", "tenant_id", "status"),
    )
