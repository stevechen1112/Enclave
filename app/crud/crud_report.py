"""
Phase 11-2 — CRUD helpers for GeneratedReport.
"""

import uuid
from typing import Optional, List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import desc, or_, func
from app.models.generated_report import GeneratedReport


def create_report(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    created_by: uuid.UUID,
    title: str,
    template: str,
    prompt: str,
    content: str,
    context_query: Optional[str] = None,
    sources: Optional[list] = None,
    document_ids: Optional[list] = None,
) -> GeneratedReport:
    word_count = len(content)
    report = GeneratedReport(
        tenant_id=tenant_id,
        created_by=created_by,
        title=title,
        template=template,
        prompt=prompt,
        context_query=context_query,
        content=content,
        word_count=word_count,
        sources=sources or [],
        document_ids=document_ids or [],
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


def get_report(
    db: Session,
    *,
    report_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> Optional[GeneratedReport]:
    return (
        db.query(GeneratedReport)
        .filter(
            GeneratedReport.id == report_id,
            GeneratedReport.tenant_id == tenant_id,
        )
        .first()
    )


def list_reports(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    created_by: Optional[uuid.UUID] = None,
    template: Optional[str] = None,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 20,
) -> Tuple[List[GeneratedReport], int]:
    """Return (reports, total_count) with optional filters."""
    q = db.query(GeneratedReport).filter(GeneratedReport.tenant_id == tenant_id)

    if created_by:
        q = q.filter(GeneratedReport.created_by == created_by)
    if template:
        q = q.filter(GeneratedReport.template == template)
    if search:
        like = f"%{search}%"
        q = q.filter(
            or_(
                GeneratedReport.title.ilike(like),
                GeneratedReport.prompt.ilike(like),
                GeneratedReport.content.ilike(like),
            )
        )

    total = q.count()
    reports = (
        q.order_by(
            desc(GeneratedReport.is_pinned),
            desc(GeneratedReport.created_at),
        )
        .offset(skip)
        .limit(limit)
        .all()
    )
    return reports, total


def update_report(
    db: Session,
    *,
    report: GeneratedReport,
    title: Optional[str] = None,
    is_pinned: Optional[bool] = None,
    content: Optional[str] = None,
) -> GeneratedReport:
    if title is not None:
        report.title = title
    if is_pinned is not None:
        report.is_pinned = is_pinned
    if content is not None:
        report.content = content
        report.word_count = len(content)
    db.commit()
    db.refresh(report)
    return report


def delete_report(
    db: Session,
    *,
    report: GeneratedReport,
) -> None:
    db.delete(report)
    db.commit()
