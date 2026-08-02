"""Phase 3 — PipesHub Connector & Source ACL models."""
import uuid
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, func, Text, Boolean, JSON, Index, UniqueConstraint
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
