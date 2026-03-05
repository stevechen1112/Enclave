"""
Phase 13 — Celery tasks for Knowledge Base Maintenance

Tasks:
  - kb_backup_task           P13-7  Full / incremental KB backup
  - kb_restore_task          P13-7  Restore from a backup archive
  - integrity_check_task     P13-6  Scan for orphan chunks / missing embeddings
  - detect_knowledge_gaps    P13-4  Scan recent low-confidence answers
"""
import gzip
import json
import logging
import os
import shutil
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
#  P13-7: Knowledge-Base Backup
# ═══════════════════════════════════════════════════════════════════════════════

BACKUP_DIR = os.environ.get("KB_BACKUP_DIR", "/data/backups/kb")


@celery_app.task(name="tasks.kb_backup", bind=True, max_retries=1)
def kb_backup_task(self, backup_id: str, backup_type: str = "full"):
    """
    Export all documents + chunks metadata to a compressed JSON archive.
    Physical files are copied alongside.  The result path is recorded in
    the KBBackup row.
    """
    from app.models.kb_maintenance import KBBackup
    from app.models.document import Document, DocumentChunk

    db: Session = SessionLocal()
    try:
        backup = db.query(KBBackup).filter(KBBackup.id == uuid.UUID(backup_id)).first()
        if not backup:
            logger.error("KBBackup %s not found", backup_id)
            return

        os.makedirs(BACKUP_DIR, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        archive_name = f"kb_backup_{ts}_{backup_id[:8]}"
        archive_dir = os.path.join(BACKUP_DIR, archive_name)
        os.makedirs(archive_dir, exist_ok=True)

        # 1. Export document metadata (tenant-scoped)
        docs_q = db.query(Document)
        if backup.tenant_id:
            docs_q = docs_q.filter(Document.tenant_id == backup.tenant_id)
        docs = docs_q.all()
        doc_records = []
        for d in docs:
            doc_records.append({
                "id": str(d.id),
                "tenant_id": str(d.tenant_id),
                "filename": d.filename,
                "file_type": d.file_type,
                "file_path": d.file_path,
                "file_size": d.file_size,
                "version": d.version,
                "status": d.status,
                "chunk_count": d.chunk_count,
                "department_id": str(d.department_id) if d.department_id else None,
                "created_at": d.created_at.isoformat() if d.created_at else None,
                "updated_at": d.updated_at.isoformat() if d.updated_at else None,
            })

        # 2. Export chunk metadata (without embedding vectors for size)
        chunks_q = db.query(
            DocumentChunk.id,
            DocumentChunk.document_id,
            DocumentChunk.chunk_index,
            DocumentChunk.text,
            DocumentChunk.chunk_hash,
            DocumentChunk.metadata_json,
        )
        if backup.tenant_id:
            chunks_q = chunks_q.filter(DocumentChunk.tenant_id == backup.tenant_id)
        chunks = chunks_q.all()
        chunk_records = []
        for c in chunks:
            chunk_records.append({
                "id": str(c.id),
                "document_id": str(c.document_id),
                "chunk_index": c.chunk_index,
                "text": c.text,
                "chunk_hash": c.chunk_hash,
                "metadata_json": c.metadata_json,
            })

        manifest = {
            "backup_id": backup_id,
            "backup_type": backup_type,
            "tenant_id": str(backup.tenant_id) if backup.tenant_id else None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "document_count": len(doc_records),
            "chunk_count": len(chunk_records),
        }

        # Write compressed JSON files
        for name, data in [("manifest", manifest), ("documents", doc_records), ("chunks", chunk_records)]:
            path = os.path.join(archive_dir, f"{name}.json.gz")
            with gzip.open(path, "wt", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)

        # 3. Copy physical files
        files_dir = os.path.join(archive_dir, "files")
        os.makedirs(files_dir, exist_ok=True)
        copied_count = 0
        for d in doc_records:
            src = d.get("file_path")
            if src and os.path.isfile(src):
                dst = os.path.join(files_dir, os.path.basename(src))
                try:
                    shutil.copy2(src, dst)
                    copied_count += 1
                except Exception as e:
                    logger.warning("Could not copy %s: %s", src, e)

        # 4. Compute total archive size
        total_size = 0
        for root, _dirs, fnames in os.walk(archive_dir):
            for fn in fnames:
                total_size += os.path.getsize(os.path.join(root, fn))

        # 5. Update record
        backup.status = "completed"
        backup.file_path = archive_dir
        backup.file_size_bytes = total_size
        backup.document_count = len(doc_records)
        backup.chunk_count = len(chunk_records)
        backup.completed_at = datetime.now(timezone.utc)
        db.commit()

        logger.info(
            "KB backup %s complete: %d docs, %d chunks, %d files, %s bytes",
            backup_id, len(doc_records), len(chunk_records), copied_count, total_size,
        )

    except Exception as exc:
        db.rollback()
        try:
            backup = db.query(KBBackup).filter(KBBackup.id == uuid.UUID(backup_id)).first()
            if backup:
                backup.status = "failed"
                backup.error_message = str(exc)[:500]
                backup.completed_at = datetime.now(timezone.utc)
                db.commit()
        except Exception:
            pass
        logger.exception("KB backup %s failed", backup_id)
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()


@celery_app.task(name="tasks.kb_restore", bind=True, max_retries=0)
def kb_restore_task(self, backup_id: str):
    """
    Restore documents + chunks from a backup archive.
    This is a destructive operation: existing data for the same doc IDs
    will be overwritten.
    """
    from app.models.kb_maintenance import KBBackup
    from app.models.document import Document, DocumentChunk

    db: Session = SessionLocal()
    try:
        backup = db.query(KBBackup).filter(KBBackup.id == uuid.UUID(backup_id)).first()
        if not backup or not backup.file_path:
            logger.error("KBBackup %s not found or no file_path", backup_id)
            return

        archive_dir = backup.file_path

        # Read manifest
        with gzip.open(os.path.join(archive_dir, "manifest.json.gz"), "rt") as f:
            manifest = json.load(f)

        # Read documents
        with gzip.open(os.path.join(archive_dir, "documents.json.gz"), "rt") as f:
            doc_records = json.load(f)

        # Read chunks
        with gzip.open(os.path.join(archive_dir, "chunks.json.gz"), "rt") as f:
            chunk_records = json.load(f)

        backup_tenant = backup.tenant_id
        restored_docs = 0
        restored_chunks = 0
        doc_tenant_by_id: dict[uuid.UUID, uuid.UUID] = {}

        for dr in doc_records:
            dr_tenant = uuid.UUID(dr["tenant_id"])
            if backup_tenant and dr_tenant != backup_tenant:
                continue

            doc_id = uuid.UUID(dr["id"])
            doc_tenant_by_id[doc_id] = dr_tenant
            existing = db.query(Document).filter(Document.id == doc_id).first()
            if existing:
                # Update in place
                for key in ["filename", "file_type", "file_path", "file_size", "version", "status", "chunk_count"]:
                    if dr.get(key) is not None:
                        setattr(existing, key, dr[key])
            else:
                doc = Document(
                    id=doc_id,
                    tenant_id=dr_tenant,
                    filename=dr["filename"],
                    file_type=dr.get("file_type"),
                    file_path=dr.get("file_path"),
                    file_size=dr.get("file_size"),
                    version=dr.get("version", 1),
                    status=dr.get("status", "completed"),
                    chunk_count=dr.get("chunk_count"),
                )
                db.add(doc)
            restored_docs += 1

        db.flush()

        for cr in chunk_records:
            chunk_id = uuid.UUID(cr["id"])
            chunk_doc_id = uuid.UUID(cr["document_id"])
            chunk_tenant_id = doc_tenant_by_id.get(chunk_doc_id)
            if backup_tenant and chunk_tenant_id and chunk_tenant_id != backup_tenant:
                continue

            existing = db.query(DocumentChunk).filter(DocumentChunk.id == chunk_id).first()
            if not existing:
                chunk = DocumentChunk(
                    id=chunk_id,
                    document_id=chunk_doc_id,
                    tenant_id=chunk_tenant_id,
                    chunk_index=cr["chunk_index"],
                    text=cr["text"],
                    chunk_hash=cr.get("chunk_hash"),
                    metadata_json=cr.get("metadata_json"),
                )
                db.add(chunk)
                restored_chunks += 1

        db.commit()

        logger.info(
            "KB restore from %s complete: %d docs, %d new chunks",
            backup_id, restored_docs, restored_chunks,
        )

    except Exception as exc:
        db.rollback()
        logger.exception("KB restore %s failed", backup_id)
        raise
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════════
#  P13-6: Index Integrity Check
# ═══════════════════════════════════════════════════════════════════════════════

STALE_THRESHOLD_DAYS = int(os.environ.get("KB_STALE_THRESHOLD_DAYS", "90"))


@celery_app.task(name="tasks.integrity_check", bind=True, max_retries=0)
def integrity_check_task(self, tenant_id: str | None = None):
    """
    Scan the KB for inconsistencies:
      - orphan chunks (document_id references a non-existent document)
      - missing embeddings (chunk.embedding IS NULL)
      - failed documents (status = 'failed')
      - stale documents (not updated in > threshold days)
    """
    from app.models.kb_maintenance import IntegrityReport
    from app.models.document import Document, DocumentChunk

    db: Session = SessionLocal()
    try:
        report = IntegrityReport(
            tenant_id=uuid.UUID(tenant_id) if tenant_id else None,
        )
        db.add(report)
        db.flush()

        base_doc_q = db.query(Document)
        base_chunk_q = db.query(DocumentChunk)
        if tenant_id:
            tid = uuid.UUID(tenant_id)
            base_doc_q = base_doc_q.filter(Document.tenant_id == tid)
            base_chunk_q = base_chunk_q.filter(DocumentChunk.tenant_id == tid)

        total_docs = base_doc_q.count()
        total_chunks = base_chunk_q.count()

        # Orphan chunks: chunks whose document no longer exists
        orphan_q = base_chunk_q.filter(
            ~DocumentChunk.document_id.in_(
                db.query(Document.id)
            )
        )
        orphan_count = orphan_q.count()

        # Missing embeddings
        missing_emb = base_chunk_q.filter(DocumentChunk.embedding.is_(None)).count()

        # Failed documents
        failed_docs = base_doc_q.filter(Document.status == "failed").count()

        # Stale documents
        stale_cutoff = datetime.now(timezone.utc) - timedelta(days=STALE_THRESHOLD_DAYS)
        stale_q = base_doc_q.filter(
            Document.status == "completed",
            func.coalesce(Document.updated_at, Document.created_at) < stale_cutoff,
        )
        stale_docs = stale_q.count()

        # Build detail
        detail = {
            "stale_threshold_days": STALE_THRESHOLD_DAYS,
            "orphan_chunk_ids": [str(c.id) for c in orphan_q.limit(100).all()],
            "failed_doc_ids": [
                str(d.id) for d in base_doc_q.filter(Document.status == "failed").limit(100).all()
            ],
        }

        report.status = "completed"
        report.total_documents = total_docs
        report.total_chunks = total_chunks
        report.orphan_chunks = orphan_count
        report.missing_embeddings = missing_emb
        report.failed_documents = failed_docs
        report.stale_documents = stale_docs
        report.detail_json = detail
        report.completed_at = datetime.now(timezone.utc)
        db.commit()

        logger.info(
            "Integrity check complete: %d docs, %d chunks, %d orphans, %d missing emb, %d failed, %d stale",
            total_docs, total_chunks, orphan_count, missing_emb, failed_docs, stale_docs,
        )
        return str(report.id)

    except Exception as exc:
        db.rollback()
        logger.exception("Integrity check failed")
        raise
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════════
#  P13-4: Knowledge Gap Detection
# ═══════════════════════════════════════════════════════════════════════════════

GAP_CONFIDENCE_THRESHOLD = float(os.environ.get("KB_GAP_CONFIDENCE_THRESHOLD", "0.35"))


@celery_app.task(name="tasks.detect_knowledge_gaps", bind=True, max_retries=0)
def detect_knowledge_gaps_task(self, tenant_id: str | None = None, days: int = 7):
    """
    Scan RetrievalTrace records from the past N days, identify queries
    where confidence was below threshold, and create KnowledgeGap records.
    """
    from app.models.kb_maintenance import KnowledgeGap
    from app.models.chat import RetrievalTrace, Message

    db: Session = SessionLocal()
    try:
        since = datetime.now(timezone.utc) - timedelta(days=days)

        q = db.query(RetrievalTrace).filter(
            RetrievalTrace.created_at >= since if hasattr(RetrievalTrace, "created_at") else True,
        )
        if tenant_id:
            q = q.filter(RetrievalTrace.tenant_id == uuid.UUID(tenant_id))

        gap_count = 0
        for trace in q.all():
            sources = trace.sources_json or []
            if not sources:
                continue

            # Compute average confidence from sources
            scores = []
            for src in sources:
                score = src.get("score") or src.get("confidence") or src.get("similarity")
                if score is not None:
                    scores.append(float(score))

            if not scores:
                continue

            avg_score = sum(scores) / len(scores)
            if avg_score >= GAP_CONFIDENCE_THRESHOLD:
                continue

            # Get the user query from the Message
            msg = db.query(Message).filter(
                Message.id == trace.message_id,
                Message.role == "user",
            ).first()
            if not msg:
                # Try to get the previous user message in the conversation
                msg = db.query(Message).filter(
                    Message.conversation_id == trace.conversation_id,
                    Message.role == "user",
                ).order_by(Message.created_at.desc()).first()

            query_text = msg.content if msg else "Unknown query"

            # Avoid duplicates: check if similar gap exists recently
            existing = db.query(KnowledgeGap).filter(
                KnowledgeGap.tenant_id == trace.tenant_id,
                KnowledgeGap.query_text == query_text,
                KnowledgeGap.status == "open",
            ).first()
            if existing:
                continue

            gap = KnowledgeGap(
                tenant_id=trace.tenant_id,
                query_text=query_text[:1000],
                confidence_score=round(avg_score, 4),
                conversation_id=trace.conversation_id,
                message_id=trace.message_id,
            )
            db.add(gap)
            gap_count += 1

        db.commit()
        logger.info("Knowledge gap scan complete: %d new gaps found", gap_count)
        return gap_count

    except Exception as exc:
        db.rollback()
        logger.exception("Knowledge gap detection failed")
        raise
    finally:
        db.close()
