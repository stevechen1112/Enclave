"""Phase 4 — WeKnora Wiki derivative projection models."""
import uuid
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, func, Text, JSON, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base_class import Base

WIKI_PAGE_TYPES = ("summary", "entity", "concept", "index", "synthesis", "comparison")


class WikiPage(Base):
    __tablename__ = "wiki_pages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    kb_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_bases.id"), nullable=True, index=True)
    slug = Column(String, nullable=False, index=True)
    title = Column(String, nullable=False)
    page_type = Column(String, nullable=False)  # summary | entity | concept | index | synthesis | comparison
    status = Column(String, default="draft")  # draft | published | stale | tombstoned | failed
    active_revision = Column(Integer, default=1)
    provider = Column(String, default="weknora")
    provider_page_id = Column(String, nullable=True)
    source_document_ids = Column(JSON, default=list)
    backlinks = Column(JSON, default=list)
    tombstoned_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    revisions = relationship("WikiRevision", back_populates="page", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_wiki_slug"),
    )


class WikiRevision(Base):
    __tablename__ = "wiki_revisions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    wiki_page_id = Column(UUID(as_uuid=True), ForeignKey("wiki_pages.id"), nullable=False, index=True)
    revision = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    content_hash = Column(String, nullable=True)
    citation_map = Column(JSON, default=list)  # [{document_id, revision, chunk_id, page, bbox}]
    compile_job_id = Column(String, nullable=True)
    status = Column(String, default="active")  # active | superseded
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    page = relationship("WikiPage", back_populates="revisions")

    __table_args__ = (
        UniqueConstraint("wiki_page_id", "revision", name="uq_wiki_revision"),
    )
