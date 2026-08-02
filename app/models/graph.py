"""Phase 4 — Graph projection (PostgreSQL adjacency model)."""
import uuid
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, func, Text, JSON, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from app.db.base_class import Base


class GraphEntity(Base):
    __tablename__ = "graph_entities"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    kb_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_bases.id"), nullable=True, index=True)
    namespace = Column(String, nullable=False, default="weknora")  # weknora | pipeshub
    entity_type = Column(String, nullable=False)
    name = Column(String, nullable=False, index=True)
    source_document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=True)
    source_revision = Column(Integer, nullable=True)
    acl_fingerprint = Column(String, nullable=True)
    provider_entity_id = Column(String, nullable=True)
    metadata_json = Column(JSON, default=dict)
    tombstoned_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("ix_graph_entity_ns", "tenant_id", "namespace", "name"),
    )


class GraphEdge(Base):
    __tablename__ = "graph_edges"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    namespace = Column(String, nullable=False, default="weknora")
    source_entity_id = Column(UUID(as_uuid=True), ForeignKey("graph_entities.id"), nullable=False, index=True)
    target_entity_id = Column(UUID(as_uuid=True), ForeignKey("graph_entities.id"), nullable=False, index=True)
    relation_type = Column(String, nullable=False)
    weight = Column(Integer, default=1)
    source_revision = Column(Integer, nullable=True)
    acl_fingerprint = Column(String, nullable=True)
    metadata_json = Column(JSON, default=dict)
    tombstoned_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "namespace", "source_entity_id", "target_entity_id", "relation_type",
            name="uq_graph_edge",
        ),
    )
