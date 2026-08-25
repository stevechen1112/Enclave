"""Tenant-scoped DB API for governed know-how cards."""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api import deps
from app.api.deps_permissions import (
    allow_all_authenticated,
    require_admin,
    require_knowhow_author,
)
from app.models.user import User
from app.services.mka_persistence import (
    MKAConflictError,
    MKAForbiddenError,
    MKANotFoundError,
    MKARepository,
    approval_to_dict,
    knowhow_to_dict,
)
from app.services.knowhow_lifecycle import get_knowhow_lifecycle_manager

router = APIRouter(prefix="/knowhow", tags=["knowhow"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


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
    current_user: User = Depends(require_knowhow_author),
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
            owner_id=current_user.id,
        )
        db.commit()
        db.refresh(row)
        return knowhow_to_dict(row)
    except Exception as exc:
        db.rollback()
        _raise_mka(exc)


def _can_read_knowhow(row, user: User) -> bool:
    """核准卡全租戶可讀；非核准狀態僅擁有者／owner/admin/superuser 可讀。"""
    if row.status == "approved":
        return True
    if user.is_superuser or user.role in {"owner", "admin"}:
        return True
    return row.owner_id is not None and row.owner_id == user.id


@router.get("")
def list_knowhow(
    status: Optional[str] = None,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(allow_all_authenticated),
):
    rows = MKARepository(db).list_knowhow(
        tenant_id=current_user.tenant_id, status=status
    )
    return [knowhow_to_dict(row) for row in rows if _can_read_knowhow(row, current_user)]


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
        if not _can_read_knowhow(row, current_user):
            raise MKAForbiddenError("know-how card is not approved")
        return knowhow_to_dict(row)
    except Exception as exc:
        _raise_mka(exc)


@router.patch("/{knowhow_id}")
def patch_knowhow(
    knowhow_id: UUID,
    request: KnowhowPatchRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_knowhow_author),
):
    try:
        row = MKARepository(db).update_knowhow(
            tenant_id=current_user.tenant_id,
            knowhow_id=knowhow_id,
            expected_version=request.version,
            data=request.values,
            actor_id=current_user.id,
            actor_roles=[current_user.role],
            is_superuser=bool(current_user.is_superuser),
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
    current_user: User = Depends(require_knowhow_author),
):
    try:
        row, approval = MKARepository(db).submit_knowhow(
            tenant_id=current_user.tenant_id,
            knowhow_id=knowhow_id,
            submitted_by=current_user.id,
            expected_version=request.version,
            idempotency_key=request.idempotency_key,
            actor_roles=[current_user.role],
            is_superuser=bool(current_user.is_superuser),
        )
        db.commit()
        db.refresh(row)
        db.refresh(approval)
        return {
            "knowhow": knowhow_to_dict(row),
            "approval": approval_to_dict(approval),
        }
    except MKAConflictError as exc:
        db.rollback()
        # 衝突報告必須存活於 409 之後，否則 UI 永遠看不到待處置項目
        report = getattr(exc, "conflict_report", None)
        if report is not None:
            try:
                row = MKARepository(db).get_knowhow(
                    tenant_id=current_user.tenant_id, knowhow_id=knowhow_id
                )
                row.conflict_report = report
                db.commit()
            except Exception:
                db.rollback()
        if report is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "unresolved_sop_conflicts",
                    "message": str(exc),
                    "conflicts": report,
                },
            )
        raise HTTPException(status_code=409, detail=str(exc))
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

        # ── Knowhow lifecycle: review reminder 與核准同一筆交易 ──
        # 若 reminder 寫入失敗，rollback 會一併撤銷核准，避免「已核准但無提醒」
        lifecycle = get_knowhow_lifecycle_manager(db=db, tenant_id=current_user.tenant_id)
        lifecycle.create_review_reminder(
            card_id=str(row.id),
            card_title=row.title,
            reviewer=str(current_user.id),
            due_at=(_now() + timedelta(days=180)).isoformat(),
            reminder_type="periodic_review",
            message=f"知識卡「{row.title}」已核准 180 天，請複核",
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

        # ── Knowhow lifecycle: purge expired audio on retire（與 retire 同交易）──
        lifecycle = get_knowhow_lifecycle_manager(db=db, tenant_id=current_user.tenant_id)
        lifecycle.purge_expired_audio(card_id=str(row.id))

        db.commit()
        db.refresh(row)

        return knowhow_to_dict(row)
    except Exception as exc:
        db.rollback()
        _raise_mka(exc)
