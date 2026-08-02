"""
Phase 0 — Knowledge Base Domain Model

新增 KB 領域模型以支援：
  - 多 KB 管理（每租戶可有多個 KB）
  - KB 成員與政策
  - KB 版本修訂（manifest + policy revision）
  - Document 擴充：knowledge_base_id、source_system、source_record_id、content_hash、tombstoned_at
  - Document Artifact：追蹤每個 provider 產出的解析/索引/Wiki/Graph artifact
"""
import uuid
from sqlalchemy import (
    Column, String, Integer, DateTime, ForeignKey, func,
    Text, JSON, Boolean, UniqueConstraint, Index,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base_class import Base


# ═══════════════════════════════════════════════════════════════════════════════
#  KnowledgeBase
# ═══════════════════════════════════════════════════════════════════════════════

class KnowledgeBase(Base):
    """租戶下的知識庫。"""

    __tablename__ = "knowledge_bases"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String, default="active")  # active | archived | deleted
    policy_id = Column(UUID(as_uuid=True), nullable=True)  # FK to kb_policies (future)
    active_revision = Column(Integer, default=1)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    tenant = relationship("Tenant")
    members = relationship("KnowledgeBaseMember", back_populates="kb", cascade="all, delete-orphan")
    revisions = relationship("KnowledgeBaseRevision", back_populates="kb", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="kb", foreign_keys="Document.knowledge_base_id")


# ═══════════════════════════════════════════════════════════════════════════════
#  KnowledgeBaseMember
# ═══════════════════════════════════════════════════════════════════════════════

class KnowledgeBaseMember(Base):
    """KB 成員與權限。subject_type 可為 user / department / group。"""

    __tablename__ = "knowledge_base_members"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    kb_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_bases.id"), nullable=False, index=True)
    subject_type = Column(String, nullable=False)  # user | department | group
    subject_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    role = Column(String, nullable=False, default="reader")  # reader | contributor | admin | owner
    effect = Column(String, nullable=False, default="allow")  # allow | deny

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    kb = relationship("KnowledgeBase", back_populates="members")

    __table_args__ = (
        UniqueConstraint("kb_id", "subject_type", "subject_id", name="uq_kb_member_subject"),
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  KnowledgeBaseRevision
# ═══════════════════════════════════════════════════════════════════════════════

class KnowledgeBaseRevision(Base):
    """KB 版本修訂記錄。每次文件變更、權限變更或重建時遞增。"""

    __tablename__ = "knowledge_base_revisions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    kb_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_bases.id"), nullable=False, index=True)
    revision = Column(Integer, nullable=False)
    manifest_hash = Column(String, nullable=True)  # SHA256 of all document content_hashes
    policy_revision = Column(Integer, nullable=False, default=1)
    status = Column(String, default="active")  # active | building | superseded
    change_summary = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    kb = relationship("KnowledgeBase", back_populates="revisions")

    __table_args__ = (
        UniqueConstraint("kb_id", "revision", name="uq_kb_revision"),
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  DocumentArtifact
# ═══════════════════════════════════════════════════════════════════════════════

class DocumentArtifact(Base):
    """
    追蹤每個 provider 為同一份文件產出的 artifact。

    一份文件可能有多個 artifact：
      - RAGFlow parse artifact (page/bbox/table)
      - Enclave chunk artifact (pgvector embedding)
      - WeKnora wiki artifact
      - PipesHub connector snapshot
    """

    __tablename__ = "document_artifacts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False, index=True)
    revision = Column(Integer, nullable=False)  # document revision this artifact belongs to
    artifact_type = Column(String, nullable=False)  # parse | chunk | wiki | graph | connector_snapshot
    provider = Column(String, nullable=False)  # enclave | ragflow | weknora | pipeshub
    provider_version = Column(String, nullable=True)  # provider version string
    uri = Column(Text, nullable=True)  # provider-specific resource locator
    checksum = Column(String, nullable=True)  # SHA256 of artifact content
    status = Column(String, default="active")  # active | building | stale | tombstoned
    metadata_json = Column(JSON, default=dict)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    document = relationship("Document", back_populates="artifacts")

    __table_args__ = (
        Index("ix_doc_artifact_provider", "document_id", "provider", "artifact_type"),
    )
