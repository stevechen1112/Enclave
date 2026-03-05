"""
Phase 13 — Knowledge Base Maintenance API Endpoints

Sub-task coverage:
  P13-1  Document version history + re-upload
  P13-2  Version diff comparison
  P13-3  KB health dashboard
  P13-4  Knowledge gap detection + management
  P13-5  Category / taxonomy CRUD with versioning
  P13-6  Index integrity check
  P13-7  KB backup & restore
  P13-8  Usage statistics report
"""
import difflib
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional, Dict

import aiofiles
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, or_, desc, distinct
from sqlalchemy.orm import Session

from app.api import deps
from app.config import settings
from app.crud import crud_document
from app.models.audit import AuditLog, UsageRecord
from app.models.chat import Message, RetrievalTrace, Conversation
from app.models.document import Document as DocumentModel, DocumentChunk
from app.models.kb_maintenance import (
    Category,
    CategoryRevision,
    DocumentVersion,
    IntegrityReport,
    KBBackup,
    KnowledgeGap,
)
from app.models.permission import Department
from app.models.user import User
from app.schemas.kb_maintenance import (
    CategoryCoverage,
    CategoryCreate,
    CategoryOut,
    CategoryRevisionOut,
    CategoryUpdate,
    DepartmentUsageOut,
    DocumentReuploadIn,
    DocumentVersionOut,
    IntegrityReportOut,
    KBBackupCreateIn,
    KBBackupOut,
    KBHealthOut,
    KBRestoreIn,
    KnowledgeGapOut,
    KnowledgeGapResolveIn,
    StaleDocumentOut,
    TopDocumentOut,
    TopQueryOut,
    UsageReportOut,
    VersionDiffOut,
)
from app.tasks.document_tasks import process_document_task
from app.tasks.kb_maintenance_tasks import (
    detect_knowledge_gaps_task,
    integrity_check_task,
    kb_backup_task,
    kb_restore_task,
)

router = APIRouter()

STALE_THRESHOLD_DAYS = int(os.environ.get("KB_STALE_THRESHOLD_DAYS", "90"))


# ═══════════════════════════════════════════════════════════════════════════════
#  P13-1: Document Version History + Re-upload
# ═══════════════════════════════════════════════════════════════════════════════


@router.get(
    "/documents/{document_id}/versions",
    response_model=List[DocumentVersionOut],
    tags=["document-versions"],
)
def list_document_versions(
    document_id: uuid.UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """P13-1: List all historical versions of a document."""
    doc = _get_doc_or_404(db, document_id, current_user)
    versions = (
        db.query(DocumentVersion)
        .filter(DocumentVersion.document_id == doc.id)
        .order_by(DocumentVersion.version.desc())
        .all()
    )
    return versions


@router.post(
    "/documents/{document_id}/reupload",
    response_model=DocumentVersionOut,
    tags=["document-versions"],
)
async def reupload_document(
    document_id: uuid.UUID,
    file: UploadFile = File(...),
    change_note: Optional[str] = Query(None),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    P13-1: Upload a new version of an existing document.
    The current version is archived in DocumentVersion and the Document
    row is updated with the new file.
    """
    from app.api.deps_permissions import check_document_permission
    check_document_permission(current_user, "create")

    doc = _get_doc_or_404(db, document_id, current_user)

    # 1. Archive the current version
    # Grab text snapshot from existing chunks for future diff
    chunks = (
        db.query(DocumentChunk.text)
        .filter(DocumentChunk.document_id == doc.id)
        .order_by(DocumentChunk.chunk_index)
        .all()
    )
    content_snapshot = "\n".join(c.text for c in chunks) if chunks else None

    version_record = DocumentVersion(
        tenant_id=doc.tenant_id,
        document_id=doc.id,
        version=doc.version,
        filename=doc.filename,
        file_path=doc.file_path,
        file_size=doc.file_size,
        file_type=doc.file_type,
        chunk_count=doc.chunk_count,
        status=doc.status,
        quality_report=doc.quality_report,
        uploaded_by=doc.uploaded_by,
        content_snapshot=content_snapshot[:200_000] if content_snapshot else None,
        change_note=change_note,
    )
    db.add(version_record)

    # 2. Replace the document file
    file_content = await file.read()
    file_size = len(file_content)

    if file_size > settings.MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"文件過大（{file_size / 1024 / 1024:.2f} MB）",
        )

    file_ext = os.path.splitext(file.filename)[1].lower()
    upload_dir = os.path.join(settings.UPLOAD_DIR, str(doc.tenant_id))
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, f"{doc.id}{file_ext}")

    async with aiofiles.open(file_path, "wb") as f:
        await f.write(file_content)

    # 3. Delete old chunks so processing re-creates them
    db.query(DocumentChunk).filter(DocumentChunk.document_id == doc.id).delete()

    # 4. Update document row
    doc.version = doc.version + 1
    doc.filename = file.filename
    doc.file_size = file_size
    doc.file_path = file_path
    doc.status = "pending"
    doc.chunk_count = None
    doc.error_message = None
    doc.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(version_record)

    # 5. Trigger re-processing
    process_document_task.delay(
        document_id=str(doc.id),
        file_path=file_path,
        tenant_id=str(doc.tenant_id),
    )

    return version_record


# ═══════════════════════════════════════════════════════════════════════════════
#  P13-2: Version Diff
# ═══════════════════════════════════════════════════════════════════════════════


@router.get(
    "/documents/{document_id}/diff",
    response_model=VersionDiffOut,
    tags=["document-versions"],
)
def version_diff(
    document_id: uuid.UUID,
    old_version: int = Query(..., ge=1),
    new_version: int = Query(..., ge=1),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    P13-2: Compare two versions of a document and return a unified diff.
    """
    doc = _get_doc_or_404(db, document_id, current_user)

    def _get_text(ver: int) -> str:
        if ver == doc.version:
            # Current live version — read from chunks
            chunks = (
                db.query(DocumentChunk.text)
                .filter(DocumentChunk.document_id == doc.id)
                .order_by(DocumentChunk.chunk_index)
                .all()
            )
            return "\n".join(c.text for c in chunks)
        # Historical version — from snapshot
        vr = (
            db.query(DocumentVersion)
            .filter(
                DocumentVersion.document_id == doc.id,
                DocumentVersion.version == ver,
            )
            .first()
        )
        if not vr:
            raise HTTPException(404, f"版本 {ver} 不存在")
        return vr.content_snapshot or ""

    old_text = _get_text(old_version)
    new_text = _get_text(new_version)

    diff_lines = list(
        difflib.unified_diff(
            old_text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile=f"v{old_version}",
            tofile=f"v{new_version}",
            lineterm="",
        )
    )

    added = sum(1 for l in diff_lines if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in diff_lines if l.startswith("-") and not l.startswith("---"))

    # Simple HTML rendering
    html_parts = []
    for line in diff_lines:
        escaped = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        if line.startswith("+"):
            html_parts.append(f'<span class="diff-add">{escaped}</span>')
        elif line.startswith("-"):
            html_parts.append(f'<span class="diff-del">{escaped}</span>')
        elif line.startswith("@@"):
            html_parts.append(f'<span class="diff-hunk">{escaped}</span>')
        else:
            html_parts.append(f"<span>{escaped}</span>")
    diff_html = "<br>".join(html_parts)

    return VersionDiffOut(
        document_id=doc.id,
        filename=doc.filename,
        old_version=old_version,
        new_version=new_version,
        added_lines=added,
        removed_lines=removed,
        diff_html=diff_html,
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  P13-3: KB Health Dashboard
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/kb/health", response_model=KBHealthOut, tags=["kb-health"])
def kb_health_dashboard(
    stale_days: int = Query(STALE_THRESHOLD_DAYS, ge=1),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    P13-3: Aggregate KB health metrics for the current tenant.
    """
    _require_admin(current_user)
    tid = current_user.tenant_id
    base = db.query(DocumentModel).filter(DocumentModel.tenant_id == tid)

    total = base.count()
    completed = base.filter(DocumentModel.status == "completed").count()
    failed = base.filter(DocumentModel.status == "failed").count()

    stale_cutoff = datetime.now(timezone.utc) - timedelta(days=stale_days)
    stale_q = base.filter(
        DocumentModel.status == "completed",
        func.coalesce(DocumentModel.updated_at, DocumentModel.created_at) < stale_cutoff,
    )
    stale_count = stale_q.count()

    # Stale document list (top 50)
    stale_docs = stale_q.order_by(
        func.coalesce(DocumentModel.updated_at, DocumentModel.created_at).asc()
    ).limit(50).all()

    stale_list = []
    for sd in stale_docs:
        ts = sd.updated_at or sd.created_at
        days_old = (datetime.now(timezone.utc) - (ts.replace(tzinfo=timezone.utc) if ts and not ts.tzinfo else ts)).days if ts else 999
        dept_name = None
        if sd.department_id:
            dept = db.query(Department.name).filter(Department.id == sd.department_id).first()
            dept_name = dept[0] if dept else None
        stale_list.append(StaleDocumentOut(
            id=sd.id,
            filename=sd.filename,
            file_type=sd.file_type,
            status=sd.status,
            days_since_update=days_old,
            department_name=dept_name,
        ))

    # Index coverage
    index_pct = (completed / total * 100) if total > 0 else 100.0

    # Average confidence in last 7 days
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    avg_conf = None
    # Try to compute from retrieval traces
    try:
        traces = (
            db.query(RetrievalTrace.sources_json)
            .filter(
                RetrievalTrace.tenant_id == tid,
                RetrievalTrace.created_at >= seven_days_ago,
            )
            .all()
        )
        scores = []
        for (sj,) in traces:
            if sj:
                for src in sj:
                    s = src.get("score") or src.get("confidence") or src.get("similarity")
                    if s is not None:
                        scores.append(float(s))
        if scores:
            avg_conf = round(sum(scores) / len(scores), 4)
    except Exception:
        pass

    # Top queries (from messages)
    top_q_rows = (
        db.query(Message.content, func.count(Message.id).label("cnt"))
        .join(Conversation, Message.conversation_id == Conversation.id)
        .filter(Conversation.tenant_id == tid, Message.role == "user")
        .group_by(Message.content)
        .order_by(desc("cnt"))
        .limit(20)
        .all()
    )
    top_queries = [TopQueryOut(query_text=row[0][:200], count=row[1]) for row in top_q_rows]

    # Recent knowledge gaps count
    recent_gaps = (
        db.query(KnowledgeGap)
        .filter(KnowledgeGap.tenant_id == tid, KnowledgeGap.status == "open")
        .count()
    )

    return KBHealthOut(
        total_documents=total,
        completed_documents=completed,
        failed_documents=failed,
        stale_documents=stale_count,
        stale_threshold_days=stale_days,
        index_coverage_pct=round(index_pct, 2),
        avg_confidence_7d=avg_conf,
        stale_document_list=stale_list,
        top_queries=top_queries,
        recent_gaps=recent_gaps,
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  P13-4: Knowledge Gap Management
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/kb/gaps", response_model=List[KnowledgeGapOut], tags=["kb-health"])
def list_knowledge_gaps(
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, le=200),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """P13-4: List knowledge gap records."""
    q = db.query(KnowledgeGap).filter(KnowledgeGap.tenant_id == current_user.tenant_id)
    if status_filter:
        q = q.filter(KnowledgeGap.status == status_filter)
    return q.order_by(KnowledgeGap.created_at.desc()).limit(limit).all()


@router.post("/kb/gaps/{gap_id}/resolve", response_model=KnowledgeGapOut, tags=["kb-health"])
def resolve_knowledge_gap(
    gap_id: uuid.UUID,
    body: KnowledgeGapResolveIn,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """P13-4: Mark a knowledge gap as resolved."""
    gap = db.query(KnowledgeGap).filter(
        KnowledgeGap.id == gap_id,
        KnowledgeGap.tenant_id == current_user.tenant_id,
    ).first()
    if not gap:
        raise HTTPException(404, "知識缺口記錄不存在")
    gap.status = "resolved"
    gap.resolved_by = current_user.id
    gap.resolved_document_id = body.document_id
    gap.resolve_note = body.resolve_note
    gap.resolved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(gap)
    return gap


@router.post("/kb/gaps/scan", tags=["kb-health"])
def trigger_gap_scan(
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """P13-4: Manually trigger a knowledge gap scan."""
    _require_admin(current_user)
    detect_knowledge_gaps_task.delay(
        tenant_id=str(current_user.tenant_id),
        days=days,
    )
    return {"message": "知識缺口掃描已排程", "days": days}


# ═══════════════════════════════════════════════════════════════════════════════
#  P13-5: Category / Taxonomy CRUD with Versioning
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/kb/categories", response_model=List[CategoryOut], tags=["taxonomy"])
def list_categories(
    include_inactive: bool = Query(False),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """P13-5: List taxonomy categories (flat list; client builds tree)."""
    q = db.query(Category).filter(Category.tenant_id == current_user.tenant_id)
    if not include_inactive:
        q = q.filter(Category.is_active == True)  # noqa: E712
    return q.order_by(Category.sort_order, Category.name).all()


@router.post("/kb/categories", response_model=CategoryOut, tags=["taxonomy"], status_code=201)
def create_category(
    body: CategoryCreate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """P13-5: Create a taxonomy category."""
    _require_admin(current_user)
    _validate_category_parent(db, current_user.tenant_id, None, body.parent_id)

    cat = Category(
        tenant_id=current_user.tenant_id,
        name=body.name,
        description=body.description,
        parent_id=body.parent_id,
        sort_order=body.sort_order,
    )
    db.add(cat)
    db.flush()

    # Record revision
    _record_category_revision(db, cat, "create", None, current_user.id)
    db.commit()
    db.refresh(cat)
    return cat


@router.put("/kb/categories/{cat_id}", response_model=CategoryOut, tags=["taxonomy"])
def update_category(
    cat_id: uuid.UUID,
    body: CategoryUpdate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """P13-5: Update a category (name, parent, active, etc.)."""
    _require_admin(current_user)
    cat = db.query(Category).filter(
        Category.id == cat_id,
        Category.tenant_id == current_user.tenant_id,
    ).first()
    if not cat:
        raise HTTPException(404, "分類不存在")

    before = _cat_snapshot(cat)
    action = "rename"

    if body.name is not None:
        cat.name = body.name
    if body.description is not None:
        cat.description = body.description
    if body.parent_id is not None:
        _validate_category_parent(db, current_user.tenant_id, cat.id, body.parent_id)
        cat.parent_id = body.parent_id
        action = "move"
    if body.sort_order is not None:
        cat.sort_order = body.sort_order
    if body.is_active is not None:
        cat.is_active = body.is_active
        action = "deactivate" if not body.is_active else "activate"

    _record_category_revision(db, cat, action, before, current_user.id)
    db.commit()
    db.refresh(cat)
    return cat


@router.delete("/kb/categories/{cat_id}", status_code=204, tags=["taxonomy"])
def delete_category(
    cat_id: uuid.UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """P13-5: Soft-delete (deactivate) a category."""
    _require_admin(current_user)
    cat = db.query(Category).filter(
        Category.id == cat_id,
        Category.tenant_id == current_user.tenant_id,
    ).first()
    if not cat:
        raise HTTPException(404, "分類不存在")
    before = _cat_snapshot(cat)
    cat.is_active = False
    _record_category_revision(db, cat, "delete", before, current_user.id)
    db.commit()
    return None


@router.get(
    "/kb/categories/{cat_id}/revisions",
    response_model=List[CategoryRevisionOut],
    tags=["taxonomy"],
)
def list_category_revisions(
    cat_id: uuid.UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """P13-5: List revision history for a category."""
    revisions = (
        db.query(CategoryRevision)
        .filter(
            CategoryRevision.category_id == cat_id,
            CategoryRevision.tenant_id == current_user.tenant_id,
        )
        .order_by(CategoryRevision.revision.desc())
        .all()
    )
    return revisions


@router.post(
    "/kb/categories/{cat_id}/rollback/{revision}",
    response_model=CategoryOut,
    tags=["taxonomy"],
)
def rollback_category(
    cat_id: uuid.UUID,
    revision: int,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """P13-5: Rollback a category to a previous revision."""
    rev = db.query(CategoryRevision).filter(
        CategoryRevision.category_id == cat_id,
        CategoryRevision.revision == revision,
        CategoryRevision.tenant_id == current_user.tenant_id,
    ).first()
    if not rev:
        raise HTTPException(404, "修訂版本不存在")

    cat = db.query(Category).filter(Category.id == cat_id).first()
    if not cat:
        raise HTTPException(404, "分類不存在")

    snapshot = rev.before_json or rev.after_json
    if not snapshot:
        raise HTTPException(400, "此修訂版本無快照資料")

    before = _cat_snapshot(cat)
    cat.name = snapshot.get("name", cat.name)
    cat.description = snapshot.get("description", cat.description)
    cat.parent_id = uuid.UUID(snapshot["parent_id"]) if snapshot.get("parent_id") else cat.parent_id
    cat.sort_order = snapshot.get("sort_order", cat.sort_order)
    cat.is_active = snapshot.get("is_active", True)

    _record_category_revision(db, cat, "rollback", before, current_user.id)
    db.commit()
    db.refresh(cat)
    return cat


# ═══════════════════════════════════════════════════════════════════════════════
#  P13-6: Index Integrity Check
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/kb/integrity/scan", tags=["kb-health"])
def trigger_integrity_check(
    current_user: User = Depends(deps.get_current_active_user),
):
    """P13-6: Trigger an integrity check scan."""
    _require_admin(current_user)
    integrity_check_task.delay(tenant_id=str(current_user.tenant_id))
    return {"message": "索引完整性檢查已排程"}


@router.get("/kb/integrity/reports", response_model=List[IntegrityReportOut], tags=["kb-health"])
def list_integrity_reports(
    limit: int = Query(10, le=50),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """P13-6: List recent integrity scan reports."""
    reports = (
        db.query(IntegrityReport)
        .filter(
            or_(
                IntegrityReport.tenant_id == current_user.tenant_id,
                IntegrityReport.tenant_id.is_(None),
            )
        )
        .order_by(IntegrityReport.started_at.desc())
        .limit(limit)
        .all()
    )
    return reports


# ═══════════════════════════════════════════════════════════════════════════════
#  P13-7: KB Backup & Restore
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/kb/backups", response_model=KBBackupOut, status_code=201, tags=["kb-backup"])
def create_backup(
    body: KBBackupCreateIn,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """P13-7: Initiate a KB backup (async via Celery)."""
    _require_admin(current_user)
    backup = KBBackup(
        tenant_id=current_user.tenant_id,
        backup_type=body.backup_type,
        status="running",
        initiated_by=current_user.id,
    )
    db.add(backup)
    db.commit()
    db.refresh(backup)

    kb_backup_task.delay(backup_id=str(backup.id), backup_type=body.backup_type)
    return backup


@router.get("/kb/backups", response_model=List[KBBackupOut], tags=["kb-backup"])
def list_backups(
    limit: int = Query(20, le=100),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """P13-7: List available backup restore points."""
    backups = (
        db.query(KBBackup)
        .filter(
            or_(
                KBBackup.tenant_id == current_user.tenant_id,
                KBBackup.tenant_id.is_(None),
            )
        )
        .order_by(KBBackup.started_at.desc())
        .limit(limit)
        .all()
    )
    return backups


@router.post("/kb/backups/restore", tags=["kb-backup"])
def restore_backup(
    body: KBRestoreIn,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """P13-7: Initiate a KB restore from a backup point (async via Celery)."""
    _require_admin(current_user)
    backup = db.query(KBBackup).filter(KBBackup.id == body.backup_id).first()
    if not backup:
        raise HTTPException(404, "備份記錄不存在")
    if not current_user.is_superuser and backup.tenant_id != current_user.tenant_id:
        raise HTTPException(403, "無權限還原此備份")
    if backup.status != "completed":
        raise HTTPException(400, "此備份未完成，無法還原")

    kb_restore_task.delay(backup_id=str(backup.id))
    return {"message": "知識庫還原已排程", "backup_id": str(backup.id)}


# ═══════════════════════════════════════════════════════════════════════════════
#  P13-8: Usage Statistics Report
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/kb/usage-report", response_model=UsageReportOut, tags=["usage-stats"])
def usage_report(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    P13-8: Generate a usage statistics report for the current tenant.
    Covers query frequency, generation counts, token usage, hot documents.
    """
    tid = current_user.tenant_id
    period_end = datetime.now(timezone.utc)
    period_start = period_end - timedelta(days=days)

    # Total queries (user messages)
    total_queries = (
        db.query(func.count(Message.id))
        .join(Conversation, Message.conversation_id == Conversation.id)
        .filter(
            Conversation.tenant_id == tid,
            Message.role == "user",
            Message.created_at >= period_start,
        )
        .scalar()
    ) or 0

    # Total generations (from usage records action_type='generate' or 'chat')
    usage_q = db.query(UsageRecord).filter(
        UsageRecord.tenant_id == tid,
        UsageRecord.created_at >= period_start,
    )
    total_generations = usage_q.filter(UsageRecord.action_type == "generate").count()
    total_tokens = (
        db.query(func.sum(UsageRecord.input_tokens + UsageRecord.output_tokens))
        .filter(UsageRecord.tenant_id == tid, UsageRecord.created_at >= period_start)
        .scalar()
    ) or 0

    # Active users
    active_users = (
        db.query(func.count(distinct(UsageRecord.user_id)))
        .filter(UsageRecord.tenant_id == tid, UsageRecord.created_at >= period_start)
        .scalar()
    ) or 0

    # Department breakdown
    dept_rows = (
        db.query(
            Department.id,
            Department.name,
            func.count(UsageRecord.id).label("cnt"),
            func.sum(UsageRecord.input_tokens + UsageRecord.output_tokens).label("toks"),
            func.count(distinct(UsageRecord.user_id)).label("users"),
        )
        .outerjoin(User, UsageRecord.user_id == User.id)
        .outerjoin(Department, User.department_id == Department.id)
        .filter(UsageRecord.tenant_id == tid, UsageRecord.created_at >= period_start)
        .group_by(Department.id, Department.name)
        .all()
    )
    dept_breakdown = []
    for row in dept_rows:
        # Separate query vs generate counts
        q_cnt = (
            db.query(func.count(UsageRecord.id))
            .outerjoin(User, UsageRecord.user_id == User.id)
            .filter(
                UsageRecord.tenant_id == tid,
                UsageRecord.created_at >= period_start,
                UsageRecord.action_type == "chat",
                User.department_id == row[0] if row[0] else User.department_id.is_(None),
            )
            .scalar()
        ) or 0
        g_cnt = (
            db.query(func.count(UsageRecord.id))
            .outerjoin(User, UsageRecord.user_id == User.id)
            .filter(
                UsageRecord.tenant_id == tid,
                UsageRecord.created_at >= period_start,
                UsageRecord.action_type == "generate",
                User.department_id == row[0] if row[0] else User.department_id.is_(None),
            )
            .scalar()
        ) or 0
        dept_breakdown.append(DepartmentUsageOut(
            department_id=row[0],
            department_name=row[1] or "未分部門",
            query_count=q_cnt,
            generate_count=g_cnt,
            total_tokens=int(row[3] or 0),
            active_users=int(row[4] or 0),
        ))

    # Top documents (by retrieval source title -> filename mapping)
    traces = (
        db.query(RetrievalTrace.sources_json)
        .filter(
            RetrievalTrace.tenant_id == tid,
            RetrievalTrace.created_at >= period_start,
        )
        .all()
    )
    filename_hits: Dict[str, int] = {}
    for (sources_json,) in traces:
        if not sources_json:
            continue
        for source in sources_json:
            title = source.get("title") if isinstance(source, dict) else None
            if title:
                filename_hits[title] = filename_hits.get(title, 0) + 1

    top_documents: List[TopDocumentOut] = []
    if filename_hits:
        sorted_titles = sorted(filename_hits.items(), key=lambda item: item[1], reverse=True)[:20]
        filenames = [name for name, _count in sorted_titles]
        docs = (
            db.query(DocumentModel)
            .filter(DocumentModel.tenant_id == tid, DocumentModel.filename.in_(filenames))
            .all()
        )
        doc_by_filename = {doc.filename: doc for doc in docs}
        for filename, hit_count in sorted_titles:
            matched_doc = doc_by_filename.get(filename)
            if not matched_doc:
                continue
            top_documents.append(
                TopDocumentOut(
                    document_id=matched_doc.id,
                    filename=matched_doc.filename,
                    query_hit_count=hit_count,
                )
            )

    # Top queries
    top_q_rows = (
        db.query(Message.content, func.count(Message.id).label("cnt"))
        .join(Conversation, Message.conversation_id == Conversation.id)
        .filter(
            Conversation.tenant_id == tid,
            Message.role == "user",
            Message.created_at >= period_start,
        )
        .group_by(Message.content)
        .order_by(desc("cnt"))
        .limit(20)
        .all()
    )
    top_queries = [TopQueryOut(query_text=r[0][:200], count=r[1]) for r in top_q_rows]

    return UsageReportOut(
        period_start=period_start,
        period_end=period_end,
        total_queries=total_queries,
        total_generations=total_generations,
        total_tokens=total_tokens,
        active_users=active_users,
        department_breakdown=dept_breakdown,
        top_documents=top_documents,
        top_queries=top_queries,
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _get_doc_or_404(db: Session, document_id: uuid.UUID, user: User) -> DocumentModel:
    doc = db.query(DocumentModel).filter(DocumentModel.id == document_id).first()
    if not doc:
        raise HTTPException(404, "文件不存在")
    if not user.is_superuser and doc.tenant_id != user.tenant_id:
        raise HTTPException(403, "無權限存取此文件")
    return doc


def _cat_snapshot(cat: Category) -> dict:
    return {
        "name": cat.name,
        "description": cat.description,
        "parent_id": str(cat.parent_id) if cat.parent_id else None,
        "sort_order": cat.sort_order,
        "is_active": cat.is_active,
    }


def _record_category_revision(
    db: Session,
    cat: Category,
    action: str,
    before: dict | None,
    user_id: uuid.UUID | None,
):
    # Get next revision number
    max_rev = (
        db.query(func.max(CategoryRevision.revision))
        .filter(CategoryRevision.category_id == cat.id)
        .scalar()
    ) or 0

    rev = CategoryRevision(
        tenant_id=cat.tenant_id,
        category_id=cat.id,
        revision=max_rev + 1,
        action=action,
        before_json=before,
        after_json=_cat_snapshot(cat),
        actor_user_id=user_id,
    )
    db.add(rev)


def _validate_category_parent(
    db: Session,
    tenant_id: uuid.UUID,
    cat_id: uuid.UUID | None,
    parent_id: uuid.UUID | None,
):
    if parent_id is None:
        return

    parent = db.query(Category).filter(
        Category.id == parent_id,
        Category.tenant_id == tenant_id,
    ).first()
    if not parent:
        raise HTTPException(status_code=400, detail="父分類不存在或不屬於同租戶")

    if cat_id is None:
        return

    if cat_id == parent_id:
        raise HTTPException(status_code=400, detail="分類不能設為自己的父節點")

    seen: set[uuid.UUID] = set()
    cursor = parent
    while cursor is not None:
        if cursor.id in seen:
            raise HTTPException(status_code=400, detail="分類樹存在循環參照")
        seen.add(cursor.id)
        if cursor.id == cat_id:
            raise HTTPException(status_code=400, detail="此父分類設定會形成循環")
        if cursor.parent_id is None:
            break
        cursor = db.query(Category).filter(
            Category.id == cursor.parent_id,
            Category.tenant_id == tenant_id,
        ).first()


def _require_admin(user: User):
    if user.role not in ("admin", "owner") and not user.is_superuser:
        raise HTTPException(status_code=403, detail="僅限管理員操作")
