"""Tenant-scoped DB API for governed know-how cards."""
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api import deps
from app.api.deps_permissions import allow_all_authenticated, require_admin
from app.models.user import User
from app.services.mka_persistence import (
    MKAConflictError,
    MKAForbiddenError,
    MKANotFoundError,
    MKARepository,
    approval_to_dict,
    knowhow_to_dict,
)

router = APIRouter(prefix="/knowhow", tags=["knowhow"])


class KnowhowCreateRequest(BaseModel):
    title: str
    summary: str = ""
    steps: List[str] = Field(default_factory=list)
    risk_level: str = "medium"
    authority_level: int = 60
    applicable_roles: List[str] = Field(default_factory=list)
    equipment_ids: List[str] = Field(default_factory=list)
    product_ids: List[str] = Field(default_factory=list)
    customer_ids: List[str] = Field(default_factory=list)
    problem_context: Optional[str] = None
    recommended_actions: List[str] = Field(default_factory=list)
    cautions: List[str] = Field(default_factory=list)
    source_quotes: List[str] = Field(default_factory=list)
    source_type: Optional[str] = None
    source_document_id: Optional[str] = None
    prerequisites: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    prohibited_actions: List[str] = Field(default_factory=list)
    related_sop_ids: List[str] = Field(default_factory=list)
    conflict_report: List[Dict[str, Any]] = Field(default_factory=list)


class KnowhowPatchRequest(BaseModel):
    version: int
    values: Dict[str, Any]


class KnowhowSubmitRequest(BaseModel):
    version: int
    idempotency_key: str


class KnowhowApproveRequest(BaseModel):
    record_version: int
    idempotency_key: str
    reason: str = ""


def _raise_mka(exc: Exception) -> None:
    if isinstance(exc, MKANotFoundError):
        raise HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, MKAForbiddenError):
        raise HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, MKAConflictError):
        raise HTTPException(status_code=409, detail=str(exc))
    raise HTTPException(status_code=400, detail=str(exc))


@router.post("")
def create_knowhow(
    request: KnowhowCreateRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(allow_all_authenticated),
):
    payload = request.dict()
    title = payload.pop("title")
    summary = payload.pop("summary")
    steps = payload.pop("steps")
    try:
        row = MKARepository(db).create_knowhow(
            tenant_id=current_user.tenant_id,
            title=title,
            summary=summary,
            steps=steps,
            data=payload,
        )
        db.commit()
        db.refresh(row)
        return knowhow_to_dict(row)
    except Exception as exc:
        db.rollback()
        _raise_mka(exc)


@router.get("")
def list_knowhow(
    status: Optional[str] = None,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(allow_all_authenticated),
):
    rows = MKARepository(db).list_knowhow(
        tenant_id=current_user.tenant_id, status=status
    )
    return [knowhow_to_dict(row) for row in rows]


@router.get("/{knowhow_id}")
def get_knowhow(
    knowhow_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(allow_all_authenticated),
):
    try:
        row = MKARepository(db).get_knowhow(
            tenant_id=current_user.tenant_id, knowhow_id=knowhow_id
        )
        return knowhow_to_dict(row)
    except Exception as exc:
        _raise_mka(exc)


@router.patch("/{knowhow_id}")
def patch_knowhow(
    knowhow_id: UUID,
    request: KnowhowPatchRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(allow_all_authenticated),
):
    try:
        row = MKARepository(db).update_knowhow(
            tenant_id=current_user.tenant_id,
            knowhow_id=knowhow_id,
            expected_version=request.version,
            data=request.values,
        )
        db.commit()
        db.refresh(row)
        return knowhow_to_dict(row)
    except Exception as exc:
        db.rollback()
        _raise_mka(exc)


@router.post("/{knowhow_id}/submit")
def submit_knowhow(
    knowhow_id: UUID,
    request: KnowhowSubmitRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(allow_all_authenticated),
):
    try:
        row, approval = MKARepository(db).submit_knowhow(
            tenant_id=current_user.tenant_id,
            knowhow_id=knowhow_id,
            submitted_by=current_user.id,
            expected_version=request.version,
            idempotency_key=request.idempotency_key,
        )
        db.commit()
        db.refresh(row)
        db.refresh(approval)
        return {
            "knowhow": knowhow_to_dict(row),
            "approval": approval_to_dict(approval),
        }
    except Exception as exc:
        db.rollback()
        _raise_mka(exc)


@router.post("/{knowhow_id}/approve")
def approve_knowhow(
    knowhow_id: UUID,
    request: KnowhowApproveRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_admin),
):
    try:
        repository = MKARepository(db)
        approval = repository.get_pending_approval_for_object(
            tenant_id=current_user.tenant_id,
            object_type="knowhow",
            object_id=knowhow_id,
        )
        approval = repository.decide_approval(
            tenant_id=current_user.tenant_id,
            approval_id=approval.id,
            reviewer_id=current_user.id,
            reviewer_roles=[current_user.role],
            expected_version=request.record_version,
            idempotency_key=request.idempotency_key,
            action="approve",
            reason=request.reason,
            is_superuser=bool(current_user.is_superuser),
        )
        row = repository.get_knowhow(
            tenant_id=current_user.tenant_id, knowhow_id=knowhow_id
        )
        db.commit()
        db.refresh(row)
        db.refresh(approval)
        return {
            "knowhow": knowhow_to_dict(row),
            "approval": approval_to_dict(approval),
        }
    except Exception as exc:
        db.rollback()
        _raise_mka(exc)


@router.post("/{knowhow_id}/retire")
def retire_knowhow(
    knowhow_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_admin),
):
    try:
        row = MKARepository(db).retire_knowhow(
            tenant_id=current_user.tenant_id, knowhow_id=knowhow_id
        )
        db.commit()
        db.refresh(row)
        return knowhow_to_dict(row)
    except Exception as exc:
        db.rollback()
        _raise_mka(exc)
