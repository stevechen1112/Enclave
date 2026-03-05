"""
Phase 11-2 — 報告管理 API

  GET    /generate/reports           — 列出我的報告（分頁 + 搜尋 + 篩選）
  GET    /generate/reports/{id}      — 查看單篇報告
  PATCH  /generate/reports/{id}      — 更新報告（標題 / 釘選 / 內容）
  DELETE /generate/reports/{id}      — 刪除報告
  POST   /generate/reports           — 手動建立報告（串流結束後由 generate.py 內部呼叫）
"""

import logging
from typing import Optional, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user, get_db
from app.crud import crud_report

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Pydantic Schemas ──────────────────────────────────────────────────────

class ReportCreate(BaseModel):
    title: str = "未命名報告"
    template: str
    prompt: str
    context_query: Optional[str] = None
    content: str
    sources: List[dict] = []
    document_ids: List[str] = []


class ReportUpdate(BaseModel):
    title: Optional[str] = None
    is_pinned: Optional[bool] = None
    content: Optional[str] = None


class ReportSummary(BaseModel):
    id: str
    title: str
    template: str
    prompt: str
    word_count: Optional[int]
    is_pinned: bool
    created_at: str

    class Config:
        from_attributes = True


class ReportDetail(BaseModel):
    id: str
    title: str
    template: str
    prompt: str
    context_query: Optional[str]
    content: str
    word_count: Optional[int]
    sources: Optional[list]
    document_ids: Optional[list]
    is_pinned: bool
    created_at: str
    updated_at: Optional[str]

    class Config:
        from_attributes = True


class ReportListResponse(BaseModel):
    reports: List[ReportSummary]
    total: int
    page: int
    page_size: int


# ── Helpers ───────────────────────────────────────────────────────────────

def _to_summary(r) -> ReportSummary:
    return ReportSummary(
        id=str(r.id),
        title=r.title,
        template=r.template,
        prompt=r.prompt[:120] + ("..." if len(r.prompt) > 120 else ""),
        word_count=r.word_count,
        is_pinned=r.is_pinned or False,
        created_at=r.created_at.isoformat() if r.created_at else "",
    )


def _to_detail(r) -> ReportDetail:
    return ReportDetail(
        id=str(r.id),
        title=r.title,
        template=r.template,
        prompt=r.prompt,
        context_query=r.context_query,
        content=r.content,
        word_count=r.word_count,
        sources=r.sources,
        document_ids=r.document_ids,
        is_pinned=r.is_pinned or False,
        created_at=r.created_at.isoformat() if r.created_at else "",
        updated_at=r.updated_at.isoformat() if r.updated_at else None,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────

@router.get("/reports", response_model=ReportListResponse)
async def list_reports(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    template: Optional[str] = None,
    search: Optional[str] = None,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """列出當前使用者的報告（分頁、篩選、搜尋）。"""
    reports, total = crud_report.list_reports(
        db,
        tenant_id=current_user.tenant_id,
        created_by=current_user.id,
        template=template,
        search=search,
        skip=(page - 1) * page_size,
        limit=page_size,
    )
    return ReportListResponse(
        reports=[_to_summary(r) for r in reports],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/reports/{report_id}", response_model=ReportDetail)
async def get_report(
    report_id: UUID,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """取得單篇報告詳情。"""
    report = crud_report.get_report(db, report_id=report_id, tenant_id=current_user.tenant_id)
    if not report:
        raise HTTPException(status_code=404, detail="報告不存在")
    return _to_detail(report)


@router.post("/reports", response_model=ReportDetail, status_code=201)
async def create_report(
    req: ReportCreate,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """手動建立報告（也可由串流結束後內部呼叫）。"""
    report = crud_report.create_report(
        db,
        tenant_id=current_user.tenant_id,
        created_by=current_user.id,
        title=req.title,
        template=req.template,
        prompt=req.prompt,
        context_query=req.context_query,
        content=req.content,
        sources=req.sources,
        document_ids=req.document_ids,
    )
    return _to_detail(report)


@router.patch("/reports/{report_id}", response_model=ReportDetail)
async def update_report(
    report_id: UUID,
    req: ReportUpdate,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """更新報告標題 / 釘選狀態 / 內容。"""
    report = crud_report.get_report(db, report_id=report_id, tenant_id=current_user.tenant_id)
    if not report:
        raise HTTPException(status_code=404, detail="報告不存在")
    report = crud_report.update_report(
        db,
        report=report,
        title=req.title,
        is_pinned=req.is_pinned,
        content=req.content,
    )
    return _to_detail(report)


@router.delete("/reports/{report_id}", status_code=204)
async def delete_report(
    report_id: UUID,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """刪除報告。"""
    report = crud_report.get_report(db, report_id=report_id, tenant_id=current_user.tenant_id)
    if not report:
        raise HTTPException(status_code=404, detail="報告不存在")
    crud_report.delete_report(db, report=report)
