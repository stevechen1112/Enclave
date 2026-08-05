"""Business approval API; intentionally separate from /agent-approvals."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api import deps
from app.api.deps_permissions import allow_all_authenticated
from app.models.user import User
from app.services.mka_persistence import (
    MKAConflictError,
    MKAForbiddenError,
    MKANotFoundError,
    MKARepository,
    approval_to_dict,
)

router = APIRouter(prefix="/approvals", tags=["mka-approvals"])


class ApprovalDecisionRequest(BaseModel):
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


def _can_review(row, user: User) -> bool:
    return bool(
        user.is_superuser
        or not row.reviewers
        or user.role in set(row.reviewers or [])
    )


@router.get("")
@router.get("/inbox")
def approval_inbox(
    status: str = "pending",
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(allow_all_authenticated),
):
    rows = MKARepository(db).list_approvals(
        tenant_id=current_user.tenant_id, status=status
    )
    return [approval_to_dict(row) for row in rows if _can_review(row, current_user)]


@router.get("/{approval_id}")
def get_approval(
    approval_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(allow_all_authenticated),
):
    try:
        row = MKARepository(db).get_approval(
            tenant_id=current_user.tenant_id, approval_id=approval_id
        )
        if not _can_review(row, current_user):
            raise MKAForbiddenError("reviewer role not allowed for current approval step")
        return approval_to_dict(row)
    except Exception as exc:
        _raise_mka(exc)


def _decide(
    *,
    action: str,
    approval_id: UUID,
    request: ApprovalDecisionRequest,
    db: Session,
    current_user: User,
):
    try:
        row = MKARepository(db).decide_approval(
            tenant_id=current_user.tenant_id,
            approval_id=approval_id,
            reviewer_id=current_user.id,
            reviewer_roles=[current_user.role],
            expected_version=request.record_version,
            idempotency_key=request.idempotency_key,
            action=action,
            reason=request.reason,
            is_superuser=bool(current_user.is_superuser),
        )
        db.commit()
        db.refresh(row)
        return approval_to_dict(row)
    except Exception as exc:
        db.rollback()
        _raise_mka(exc)


@router.post("/{approval_id}/approve")
def approve(
    approval_id: UUID,
    request: ApprovalDecisionRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(allow_all_authenticated),
):
    return _decide(
        action="approve",
        approval_id=approval_id,
        request=request,
        db=db,
        current_user=current_user,
    )


@router.post("/{approval_id}/reject")
def reject(
    approval_id: UUID,
    request: ApprovalDecisionRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(allow_all_authenticated),
):
    return _decide(
        action="reject",
        approval_id=approval_id,
        request=request,
        db=db,
        current_user=current_user,
    )


@router.post("/{approval_id}/request-changes")
def request_changes(
    approval_id: UUID,
    request: ApprovalDecisionRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(allow_all_authenticated),
):
    return _decide(
        action="request_changes",
        approval_id=approval_id,
        request=request,
        db=db,
        current_user=current_user,
    )
