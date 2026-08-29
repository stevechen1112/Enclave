"""Business approval API; intentionally separate from /agent-approvals."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api import deps
from app.api.deps_permissions import allow_all_authenticated
from app.models.user import User
from app.services.workflow_repository import (
    WorkflowConflictError,
    WorkflowForbiddenError,
    WorkflowNotFoundError,
    WorkflowRepository,
    approval_to_dict,
)

router = APIRouter(prefix="/approvals", tags=["workflow-approvals"])


class ApprovalDecisionRequest(BaseModel):
    record_version: int
    idempotency_key: str
    reason: str = ""


def _raise_workflow(exc: Exception) -> None:
    if isinstance(exc, WorkflowNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, WorkflowForbiddenError):
        raise HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, WorkflowConflictError):
        raise HTTPException(status_code=409, detail=str(exc))
    raise HTTPException(status_code=400, detail=str(exc))


def _can_review(row, user: User) -> bool:
    # fail-closed，與 decide_approval 一致：reviewers 未配置時不對所有人開放；
    # 送審人本人仍可追蹤自己的請求。
    return bool(
        user.is_superuser
        or row.submitted_by == user.id
        or user.role in set(row.reviewers or [])
    )


# ── 簽核政策設定（租戶管理員）──

class ApprovalPolicyUpsert(BaseModel):
    object_type: str  # form | knowhow | tool
    module_key: str | None = None
    risk_level: str = "medium"
    steps: list | None = None  # None = 不更動既有 steps
    timeout_policy: dict | None = None
    delegation_policy: dict | None = None


def _require_admin(user: User) -> None:
    if not (user.is_superuser or user.role in {"owner", "admin"}):
        raise HTTPException(status_code=403, detail="admin required")


def _policy_dict(row) -> dict:
    return {
        "id": str(row.id),
        "module_key": row.module_key,
        "object_type": row.object_type,
        "version": row.version,
        "status": row.status,
        "risk_level": row.risk_level,
        "steps": row.steps or [],
        "timeout_policy": row.timeout_policy or {},
        "delegation_policy": row.delegation_policy or {},
    }


@router.get("/policies")
def list_approval_policies(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(allow_all_authenticated),
):
    _require_admin(current_user)
    from app.models.workflow import ApprovalPolicy

    rows = (
        db.query(ApprovalPolicy)
        .filter(ApprovalPolicy.tenant_id == current_user.tenant_id)
        .all()
    )
    return [_policy_dict(r) for r in rows]


@router.post("/policies", status_code=201)
def upsert_approval_policy(
    body: ApprovalPolicyUpsert,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(allow_all_authenticated),
):
    """建立或更新本租戶的簽核政策（同 object_type+module_key 視為更新）。"""
    _require_admin(current_user)
    if body.object_type not in {"form", "knowhow", "tool"}:
        raise HTTPException(status_code=422, detail="invalid object_type")
    from app.models.workflow import ApprovalPolicy

    row = (
        db.query(ApprovalPolicy)
        .filter(
            ApprovalPolicy.tenant_id == current_user.tenant_id,
            ApprovalPolicy.object_type == body.object_type,
            ApprovalPolicy.module_key == body.module_key,
            ApprovalPolicy.status == "active",
        )
        .first()
    )
    if row is None:
        row = ApprovalPolicy(
            tenant_id=current_user.tenant_id,
            object_type=body.object_type,
            module_key=body.module_key,
            status="active",
        )
        db.add(row)
    row.risk_level = body.risk_level
    if body.steps is not None:
        row.steps = body.steps
    if body.timeout_policy is not None:
        row.timeout_policy = body.timeout_policy
    if body.delegation_policy is not None:
        row.delegation_policy = body.delegation_policy
    db.commit()
    db.refresh(row)
    return _policy_dict(row)


@router.get("")
@router.get("/inbox")
def approval_inbox(
    status: str = "pending",
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(allow_all_authenticated),
):
    rows = WorkflowRepository(db).list_approvals(
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
        row = WorkflowRepository(db).get_approval(
            tenant_id=current_user.tenant_id, approval_id=approval_id
        )
        if not _can_review(row, current_user):
            raise WorkflowForbiddenError("reviewer role not allowed for current approval step")
        return approval_to_dict(row)
    except Exception as exc:
        _raise_workflow(exc)


def _decide(
    *,
    action: str,
    approval_id: UUID,
    request: ApprovalDecisionRequest,
    db: Session,
    current_user: User,
):
    try:
        row = WorkflowRepository(db).decide_approval(
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
        _raise_workflow(exc)


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
