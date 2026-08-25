"""Phase 4 — Wiki API (source-document ACL enforced). API-only Beta (DD-M08)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api import deps
from app.api.deps_permissions import require_admin, require_employee
from app.api.v1.product_surface import (
    WIKI_PRODUCT_STATUS,
    apply_product_status_headers,
    with_runtime_status,
)
from app.core.authorization import AuthorizationContext
from app.models.user import User
from app.models.wiki import WikiPage, WikiRevision
from app.services.module_gate import require_module
from app.services.product_license import ProductModule
from app.services.resource_policy import get_resource_policy
from app.services.wiki_compiler import WikiCompiler

router = APIRouter(
    prefix="/wiki",
    tags=["wiki (API-only Beta)"],
)
_compiler = WikiCompiler()


def _wiki_headers(response: Response) -> None:
    apply_product_status_headers(response, with_runtime_status(WIKI_PRODUCT_STATUS))


@router.get("/product-status")
def wiki_product_status(
    response: Response,
    current_user: User = Depends(require_employee),
) -> Dict[str, Any]:
    """Honest product surface notice — no Web UI yet."""
    _ = current_user
    status = with_runtime_status(WIKI_PRODUCT_STATUS)
    apply_product_status_headers(response, status)
    return status

class WikiCompileRequest(BaseModel):
    kb_id: UUID
    page_type: str = "summary"
    source_document_ids: Optional[List[str]] = None


class WikiPageOut(BaseModel):
    id: str
    slug: str
    title: str
    page_type: str
    status: str
    active_revision: int


def _page_visible(db: Session, authz: AuthorizationContext, page: WikiPage) -> bool:
    """Visible iff every source document is readable (strict intersection)."""
    sources = [str(x) for x in (page.source_document_ids or [])]
    if not sources:
        return authz.has_kb_admin
    policy = get_resource_policy()
    allowed = policy.filter_documents_by_source_ids(db, authz, sources)
    return len(allowed) == len(sources)


@router.get("/pages", response_model=List[WikiPageOut])
def list_wiki_pages(
    response: Response,
    db: Session = Depends(deps.get_db),
    q: Optional[str] = Query(None),
    current_user: User = Depends(require_employee),
) -> Any:
    _wiki_headers(response)
    authz = AuthorizationContext.from_user(current_user)
    query = db.query(WikiPage).filter(
        WikiPage.tenant_id == current_user.tenant_id,
        WikiPage.tombstoned_at.is_(None),
    )
    if q:
        query = query.filter(WikiPage.title.ilike(f"%{q}%"))
    pages = query.order_by(WikiPage.updated_at.desc()).limit(50).all()
    return [
        WikiPageOut(
            id=str(p.id), slug=p.slug, title=p.title,
            page_type=p.page_type, status=p.status,
            active_revision=p.active_revision or 1,
        )
        for p in pages
        if _page_visible(db, authz, p)
    ]


@router.get("/pages/{page_id}")
def get_wiki_page(
    page_id: UUID,
    response: Response,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_employee),
) -> Dict[str, Any]:
    _wiki_headers(response)
    authz = AuthorizationContext.from_user(current_user)
    page = db.query(WikiPage).filter(
        WikiPage.id == page_id,
        WikiPage.tenant_id == current_user.tenant_id,
        WikiPage.tombstoned_at.is_(None),
    ).first()
    if not page or not _page_visible(db, authz, page):
        raise HTTPException(status_code=404, detail="Wiki 頁面不存在")
    rev = (
        db.query(WikiRevision)
        .filter(WikiRevision.wiki_page_id == page.id, WikiRevision.revision == page.active_revision)
        .first()
    )
    citation_map = list(rev.citation_map) if rev and rev.citation_map else []
    doc_ids = [c.get("document_id") for c in citation_map if isinstance(c, dict) and c.get("document_id")]
    if doc_ids:
        from app.models.document import Document
        rows = (
            db.query(Document.id, Document.filename)
            .filter(Document.id.in_(doc_ids))
            .all()
        )
        names = {str(r.id): r.filename for r in rows}
        for c in citation_map:
            if isinstance(c, dict) and c.get("document_id") in names:
                c.setdefault("filename", names[c["document_id"]])
    return {
        "id": str(page.id),
        "slug": page.slug,
        "title": page.title,
        "page_type": page.page_type,
        "status": page.status,
        "content": rev.content if rev else "",
        "citation_map": citation_map,
        "source_document_ids": page.source_document_ids or [],
        "backlinks": page.backlinks or [],
    }


class WikiEditRequest(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None


@router.patch("/pages/{page_id}", response_model=WikiPageOut)
def edit_wiki_page(
    page_id: UUID,
    body: WikiEditRequest,
    response: Response,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_admin),
) -> Any:
    """管理員手動編輯（新增 revision，不覆寫歷史）。"""
    _wiki_headers(response)
    page = db.query(WikiPage).filter(
        WikiPage.id == page_id,
        WikiPage.tenant_id == current_user.tenant_id,
        WikiPage.tombstoned_at.is_(None),
    ).first()
    if not page:
        raise HTTPException(status_code=404, detail="Wiki 頁面不存在")
    if body.title is None and body.content is None:
        raise HTTPException(status_code=400, detail="未提供要更新的欄位")
    page = _compiler.edit_page(
        db, page,
        title=body.title, content=body.content,
        editor_id=str(current_user.id),
    )
    return WikiPageOut(
        id=str(page.id), slug=page.slug, title=page.title,
        page_type=page.page_type, status=page.status,
        active_revision=page.active_revision or 1,
    )


@router.post("/compile", response_model=WikiPageOut)
def compile_wiki(
    body: WikiCompileRequest,
    response: Response,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_admin),
) -> Any:
    _wiki_headers(response)
    require_module(ProductModule.KNOWLEDGE_COMPILER)
    authz = AuthorizationContext.from_user(current_user)
    policy = get_resource_policy()
    sources = [str(x) for x in (body.source_document_ids or [])]
    if sources:
        allowed = policy.filter_documents_by_source_ids(db, authz, sources)
        if len(allowed) != len(sources):
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "source_document_access_denied",
                    "requested": sources,
                    "allowed": allowed,
                },
            )
    page = _compiler.compile_kb(
        db,
        tenant_id=current_user.tenant_id,
        kb_id=body.kb_id,
        page_type=body.page_type,
        source_document_ids=body.source_document_ids,
    )
    return WikiPageOut(
        id=str(page.id), slug=page.slug, title=page.title,
        page_type=page.page_type, status=page.status,
        active_revision=page.active_revision or 1,
    )
