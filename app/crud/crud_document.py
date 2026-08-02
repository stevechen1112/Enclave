import os
import hashlib
from datetime import datetime, timezone
from typing import List
from uuid import UUID
from sqlalchemy.orm import Session
from app.models.document import Document, DocumentChunk
from app.schemas.document import DocumentCreate, DocumentUpdate


def get(db: Session, document_id: UUID) -> Document:
    return db.query(Document).filter(
        Document.id == document_id,
        Document.tombstoned_at.is_(None),
    ).first()


def get_by_tenant(db: Session, tenant_id: UUID, skip: int = 0, limit: int = 100) -> List[Document]:
    return db.query(Document).filter(
        Document.tenant_id == tenant_id,
        Document.tombstoned_at.is_(None),
    ).offset(skip).limit(limit).all()


def create(db: Session, *, obj_in: DocumentCreate, tenant_id: UUID, uploaded_by: UUID, file_size: int) -> Document:
    db_obj = Document(
        filename=obj_in.filename,
        file_type=obj_in.file_type,
        tenant_id=tenant_id,
        uploaded_by=uploaded_by,
        file_size=file_size,
        status="uploading"
    )
    db.add(db_obj)
    db.flush()

    from app.services.outbox_events import publish_event
    publish_event(
        db,
        aggregate_type="document",
        aggregate_id=str(db_obj.id),
        event_type="created",
        revision=1,
        payload={
            "filename": db_obj.filename,
            "file_type": db_obj.file_type,
            "tenant_id": str(tenant_id),
            "uploaded_by": str(uploaded_by),
            "file_size": file_size,
        },
    )

    db.commit()
    db.refresh(db_obj)
    return db_obj


def update(db: Session, *, db_obj: Document, obj_in: DocumentUpdate) -> Document:
    update_data = obj_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_obj, field, value)
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj


def tombstone(db: Session, *, document_id: UUID, reason: str = "user_request") -> bool:
    """Deny-first soft delete: tombstone + outbox event for projection cleanup."""
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc or doc.tombstoned_at is not None:
        return False

    doc.tombstoned_at = datetime.now(timezone.utc)
    doc.status = "deleted"
    revision = (doc.version or 1) + 1
    doc.version = revision
    db.flush()

    from app.services.outbox_events import publish_event
    publish_event(
        db,
        aggregate_type="document",
        aggregate_id=str(document_id),
        event_type="deleted",
        revision=revision,
        payload={
            "filename": doc.filename,
            "tenant_id": str(doc.tenant_id),
            "reason": reason,
        },
    )

    db.commit()
    return True


def delete(db: Session, *, document_id: UUID) -> bool:
    """Backward-compatible alias — performs tombstone, not hard delete."""
    return tombstone(db, document_id=document_id)


def create_chunk(
    db: Session,
    *,
    document_id: UUID,
    tenant_id: UUID,
    chunk_index: int,
    content: str,
    vector_id: str = None
) -> DocumentChunk:
    chunk_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
    db_obj = DocumentChunk(
        document_id=document_id,
        tenant_id=tenant_id,
        chunk_index=chunk_index,
        text=content,
        chunk_hash=chunk_hash,
        vector_id=vector_id
    )
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj


def get_chunks(db: Session, document_id: UUID) -> List[DocumentChunk]:
    return db.query(DocumentChunk).filter(
        DocumentChunk.document_id == document_id
    ).order_by(DocumentChunk.chunk_index).all()
