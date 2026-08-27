import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base_class import Base


class Document(Base):
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    knowledge_base_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_bases.id"), nullable=True, index=True)

    filename = Column(String, nullable=False)
    file_type = Column(String, nullable=True)  # pdf, docx, txt
    file_path = Column(String, nullable=True) # S3 or local path
    file_size = Column(Integer, nullable=True)
    source_type = Column(String, default="file") # file, web, connector
    genre = Column(String, nullable=True, index=True)  # ADR-008 catalog 粒度：contract|voucher|manual|travel|policy|form|report|other
    source_system = Column(String, nullable=True)  # google_drive | sharepoint | nas_smb | ...
    source_record_id = Column(String, nullable=True)  # external system record ID
    external_version = Column(String, nullable=True)  # version string from source system
    content_hash = Column(String, nullable=True, index=True)  # SHA256 of original file
    version = Column(Integer, default=1)
    status = Column(String, default="pending") # upload, parsing, processing, completed, failed
    error_message = Column(Text, nullable=True)
    chunk_count = Column(Integer, nullable=True)
    quality_report = Column(JSON, nullable=True)  # QualityReport dict
    tombstoned_at = Column(DateTime(timezone=True), nullable=True)  # soft-delete timestamp

    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    department_id = Column(UUID(as_uuid=True), ForeignKey("departments.id"), nullable=True, index=True)
    # Phase B compatibility pointer. SourceAsset is canonical for new input;
    # Document remains the production model during dual-write.
    source_asset_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    tenant = relationship("Tenant", back_populates="documents")
    kb = relationship("KnowledgeBase", back_populates="documents", foreign_keys=[knowledge_base_id])
    department = relationship("Department", back_populates="documents")
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")
    artifacts = relationship("DocumentArtifact", back_populates="document", cascade="all, delete-orphan")

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "source_asset_id"],
            ["source_assets.tenant_id", "source_assets.id"],
            name="fk_documents_tenant_source_asset",
        ),
        # One active row per external record; tombstoned history may coexist.
        Index(
            "uq_documents_tenant_source_record_active",
            "tenant_id",
            "source_system",
            "source_record_id",
            unique=True,
            postgresql_where=(
                source_system.isnot(None)
                & source_record_id.isnot(None)
                & tombstoned_at.is_(None)
            ),
        ),
        Index(
            "uq_documents_tenant_source_asset",
            "tenant_id",
            "source_asset_id",
            unique=True,
            postgresql_where=(source_asset_id.isnot(None)),
        ),
    )

class DocumentChunk(Base):
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False, index=True)
    # Immutable document revision this chunk was produced from.  Old chunks are
    # retained so a KB revision never reads a newer live projection.
    document_revision = Column(Integer, nullable=False, default=1)
    
    chunk_index = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    chunk_hash = Column(String, index=True)
    vector_id = Column(String, nullable=True)      # Legacy (Pinecone), kept for backwards compat
    embedding = Column(Vector(1024), nullable=True)  # pgvector: voyage-4-lite 1024d
    metadata_json = Column(JSON, default=dict)  # page, section, etc. — use callable to avoid shared mutable default
    parent_chunk_id = Column(
        UUID(as_uuid=True),
        ForeignKey("documentchunks.id"),
        nullable=True,
        index=True,
    )

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    document = relationship("Document", back_populates="chunks")
    parent_chunk = relationship(
        "DocumentChunk",
        remote_side=[id],
        foreign_keys=[parent_chunk_id],
        back_populates="child_chunks",
    )
    child_chunks = relationship(
        "DocumentChunk",
        foreign_keys=[parent_chunk_id],
        back_populates="parent_chunk",
    )

    __table_args__ = (
        Index("ix_documentchunks_document_revision", "document_id", "document_revision"),
        # HNSW index for fast cosine similarity search
        Index(
            'ix_documentchunks_embedding_cosine',
            embedding,
            postgresql_using='hnsw',
            postgresql_with={'m': 16, 'ef_construction': 64},
            postgresql_ops={'embedding': 'vector_cosine_ops'},
        ),
        Index(
            "uq_documentchunks_document_index",
            "document_id",
            "document_revision",
            "chunk_index",
            unique=True,
        ),
        Index(
            "uq_documentchunks_document_hash",
            "document_id",
            "document_revision",
            "chunk_hash",
            unique=True,
            postgresql_where=(chunk_hash.isnot(None)),
        ),
    )
