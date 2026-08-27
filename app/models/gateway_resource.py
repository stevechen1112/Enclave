"""
Phase 1 — Gateway Resource Registry

Object-level ID mapping between Enclave canonical resources and downstream providers.
"""

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID

from app.db.base_class import Base


class GatewayResource(Base):
    """Maps Enclave resources to provider-specific resource IDs."""

    __tablename__ = "gateway_resources"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    enclave_resource_type = Column(
        String, nullable=False
    )  # document | chunk | wiki_page | graph_entity
    enclave_resource_id = Column(String, nullable=False, index=True)
    enclave_revision = Column(Integer, nullable=False, default=1)
    provider = Column(String, nullable=False)  # enclave | ragflow | weknora | pipeshub
    provider_instance_id = Column(String, nullable=True)
    provider_resource_type = Column(String, nullable=True)
    provider_resource_id = Column(String, nullable=True)
    provider_revision = Column(Integer, nullable=True, default=0)
    checksum = Column(String, nullable=True)
    state = Column(String, default="active")  # active | building | tombstoned | error
    tombstoned_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index(
            "uq_gateway_resource_mapping_nulls",
            "tenant_id",
            "enclave_resource_type",
            "enclave_resource_id",
            "provider",
            "provider_instance_id",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_gateway_resources_provider", "provider", "provider_resource_id"),
    )
