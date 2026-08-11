"""MKA Term Dictionary CRUD API — tenant-scoped term management.

§4.5 TenantTermDictionary:
  GET    /terms
  POST   /terms
  DELETE /terms/{term}
  POST   /terms/correct  (STT post-processing)
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api import deps
from app.api.deps_permissions import allow_all_authenticated, require_admin
from app.models.user import User
from app.services.term_dictionary import get_term_dictionary_service

router = APIRouter(prefix="/terms", tags=["terms"])


class TermCreateRequest(BaseModel):
    term: str
    aliases: List[str] = Field(default_factory=list)
    phonetic_hints: List[str] = Field(default_factory=list)
    category: str = "general"
    scope: str = "global"
    source: str = "manual"


class TermCorrectRequest(BaseModel):
    transcript: str


# ── Public endpoints ──

@router.get("")
def list_terms(
    category: Optional[str] = None,
    active_only: bool = True,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(allow_all_authenticated),
):
    """List tenant term dictionary entries."""
    service = get_term_dictionary_service(db)
    terms = service.list_terms(
        tenant_id=current_user.tenant_id,
        category=category,
        active_only=active_only,
    )
    return {"terms": terms, "count": len(terms)}


@router.get("/search")
def search_terms(
    q: str = Query(..., description="Search query"),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(allow_all_authenticated),
):
    """Search term dictionary (used for STT post-processing)."""
    service = get_term_dictionary_service(db)
    results = service.search_terms(
        tenant_id=current_user.tenant_id,
        query=q,
        limit=limit,
    )
    return {"results": results, "count": len(results)}


@router.post("/correct")
def correct_transcript(
    request: TermCorrectRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(allow_all_authenticated),
):
    """Apply term dictionary corrections to a transcript."""
    service = get_term_dictionary_service(db)
    corrected = service.correct_transcript(
        tenant_id=current_user.tenant_id,
        transcript=request.transcript,
    )
    return {"original": request.transcript, "corrected": corrected}


# ── Admin endpoints ──

@router.post("")
def add_term(
    request: TermCreateRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_admin),
):
    """Add or update a term in the dictionary (admin only)."""
    service = get_term_dictionary_service(db)
    result = service.add_term(
        tenant_id=current_user.tenant_id,
        term=request.term,
        aliases=request.aliases,
        phonetic_hints=request.phonetic_hints,
        category=request.category,
        scope=request.scope,
        source=request.source,
    )
    return result


@router.delete("/{term}")
def deactivate_term(
    term: str,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_admin),
):
    """Deactivate a term (admin only)."""
    service = get_term_dictionary_service(db)
    success = service.deactivate_term(
        tenant_id=current_user.tenant_id,
        term=term,
    )
    if not success:
        raise HTTPException(status_code=404, detail=f"term not found: {term}")
    return {"term": term, "active": False}
