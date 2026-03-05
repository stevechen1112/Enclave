"""
Phase 13 — Knowledge Base Maintenance Models

P13-1: DocumentVersion      — tracks document revision history
P13-5: Category / CategoryRevision — taxonomy with versioning
P13-7: KBBackup             — backup metadata & restore points
P13-4: KnowledgeGap         — knowledge gap detection records
P13-6: IntegrityReport      — index integrity scan results
"""
import uuid
from sqlalchemy import (
    Column, String, Integer, DateTime, ForeignKey, func,
    Text, JSON, Boolean, Float,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship, backref as _backref
from app.db.base_class import Base


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  P13-1: Document Version History                                           ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

class DocumentVersion(Base):
    """
    Stores a snapshot every time a document is re-uploaded or re-indexed.
    The current live version stays in the Document table; previous
    snapshots are stored here for diff / rollback.
    """
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False, index=True)

    version = Column(Integer, nullable=False)          # 1, 2, 3 …
    filename = Column(String, nullable=False)
    file_path = Column(String, nullable=True)          # archive path of this version's file
    file_size = Column(Integer, nullable=True)
    file_type = Column(String, nullable=True)
    chunk_count = Column(Integer, nullable=True)
    status = Column(String, nullable=False, default="completed")
    quality_report = Column(JSON, nullable=True)

    # Who uploaded & change note
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    change_note = Column(Text, nullable=True)          # e.g. "Updated section 3.2"

    # Text content snapshot for diff (first N chars or full text)
    content_snapshot = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    document = relationship("Document", backref="versions")


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  P13-5: Category / Taxonomy with Versioning                                ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

class Category(Base):
    """
    Hierarchical taxonomy node.  Supports arbitrary depth via parent_id.
    """
    __tablename__ = "categories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    parent_id = Column(UUID(as_uuid=True), ForeignKey("categories.id"), nullable=True, index=True)
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    document_count = Column(Integer, default=0)        # denormalised for dashboard

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    children = relationship(
        "Category",
        backref=_backref("parent", remote_side="Category.id"),
        foreign_keys=[parent_id],
    )
    revisions = relationship("CategoryRevision", backref="category", cascade="all, delete-orphan")


class CategoryRevision(Base):
    """
    P13-5: Every edit to the taxonomy tree is stored as a revision so it
    can be rolled back.
    """
    __tablename__ = "categoryrevisions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    category_id = Column(UUID(as_uuid=True), ForeignKey("categories.id"), nullable=True, index=True)

    revision = Column(Integer, nullable=False)
    action = Column(String, nullable=False)            # create / rename / move / deactivate / delete
    before_json = Column(JSON, nullable=True)          # snapshot before change
    after_json = Column(JSON, nullable=True)           # snapshot after change
    actor_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  P13-7: KB Backup Metadata                                                ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

class KBBackup(Base):
    """
    Records each backup run.  Actual backup files are on disk / object
    storage; this table stores metadata for the restore-point picker.
    """
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True, index=True)

    backup_type = Column(String, nullable=False, default="full")  # full / incremental
    status = Column(String, nullable=False, default="running")    # running / completed / failed
    file_path = Column(String, nullable=True)          # path to backup archive
    file_size_bytes = Column(Integer, nullable=True)
    document_count = Column(Integer, nullable=True)
    chunk_count = Column(Integer, nullable=True)

    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    initiated_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  P13-4: Knowledge Gap Records                                             ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

class KnowledgeGap(Base):
    """
    When the chat engine returns a low-confidence answer, a gap record is
    created so admins can see which topics need more documentation.
    """
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)

    query_text = Column(Text, nullable=False)              # The user question
    confidence_score = Column(Float, nullable=False)       # 0.0 – 1.0
    suggested_topic = Column(String, nullable=True)        # AI-extracted topic
    category_name = Column(String, nullable=True)          # Which category is missing
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=True)
    message_id = Column(UUID(as_uuid=True), ForeignKey("messages.id"), nullable=True)

    status = Column(String, default="open")                # open / acknowledged / resolved
    resolved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    resolved_document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=True)
    resolve_note = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at = Column(DateTime(timezone=True), nullable=True)


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  P13-6: Index Integrity Report                                            ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

class IntegrityReport(Base):
    """
    Result of a periodic scan that checks vector/chunk/doc consistency.
    """
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True, index=True)

    status = Column(String, nullable=False, default="running")  # running / completed / failed
    total_documents = Column(Integer, default=0)
    total_chunks = Column(Integer, default=0)

    # Problem counters
    orphan_chunks = Column(Integer, default=0)           # chunks whose document_id is missing
    missing_embeddings = Column(Integer, default=0)      # chunks with null embedding
    failed_documents = Column(Integer, default=0)        # docs stuck in failed status
    stale_documents = Column(Integer, default=0)         # docs not updated beyond threshold

    detail_json = Column(JSON, nullable=True)            # list of specific issues
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
