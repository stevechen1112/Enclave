"""Unified human-review inbox across core sources and optional product packs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api import deps
from app.models.user import User
from app.services.review_workspace import (
    decide_review_item,
    get_review_item,
    list_review_items,
)

router = APIRouter(prefix="/knowledge/review-items", tags=["knowledge-review"])


class ReviewDecisionRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    notes: str | None = Field(default=None, max_length=2000)
    acknowledge_high_risk: bool = False
    acknowledge_low_confidence: bool = False
    conflict_resolutions: dict[str, str] = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, max_length=200)


class BatchReviewRequest(BaseModel):
    item_ids: list[str] = Field(min_length=1, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)


def _require_reviewer(current_user: User) -> None:
    if not (
        current_user.is_superuser or current_user.role in {"owner", "admin"}
    ):
        raise HTTPException(status_code=403, detail="review permission required")


def _is_overdue(item: dict[str, Any]) -> bool:
    if not item.get("due_at"):
        return False
    try:
        value = datetime.fromisoformat(str(item["due_at"]).replace("Z", "+00:00"))
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value <= datetime.now(UTC)
    except ValueError:
        return True


@router.get("")
def review_inbox(
    db: Annotated[Session, Depends(deps.get_db)],
    current_user: Annotated[User, Depends(deps.get_current_active_user)],
    risk_level: str | None = Query(default=None),
    confidence_max: float | None = Query(default=None, ge=0, le=1),
    overdue: bool | None = Query(default=None),
    source_type: str | None = Query(default=None),
    department_id: str | None = Query(default=None),
    policy_key: str | None = Query(default=None),
    assignee: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    _require_reviewer(current_user)
    items = list_review_items(db, current_user=current_user)
    if risk_level:
        items = [item for item in items if item["risk_level"] == risk_level]
    if confidence_max is not None:
        items = [
            item
            for item in items
            if item["confidence"] is not None
            and float(item["confidence"]) <= confidence_max
        ]
    if overdue is not None:
        items = [item for item in items if _is_overdue(item) is overdue]
    if source_type:
        items = [item for item in items if item["source_type"] == source_type]
    if department_id:
        items = [
            item for item in items if department_id in item["department_ids"]
        ]
    if policy_key:
        items = [item for item in items if item["policy_key"] == policy_key]
    if assignee:
        items = [item for item in items if item.get("assignee") == assignee]
    priority = {"high": 0, "medium": 1, "low": 2}
    items.sort(key=lambda item: (priority.get(item["risk_level"], 9), item["due_at"] or ""))
    total = len(items)
    page = items[offset : offset + limit]
    return {
        "items": page,
        "total": total,
        "limit": limit,
        "offset": offset,
        "facets": {
            "source_types": sorted({item["source_type"] for item in items}),
            "policy_keys": sorted({item["policy_key"] for item in items}),
            "assignees": sorted({item["assignee"] for item in items if item.get("assignee")}),
        },
    }


@router.get("/{item_id}")
def review_detail(
    item_id: str,
    db: Annotated[Session, Depends(deps.get_db)],
    current_user: Annotated[User, Depends(deps.get_current_active_user)],
) -> dict[str, Any]:
    _require_reviewer(current_user)
    return get_review_item(db, current_user=current_user, item_id=item_id)


@router.post("/{item_id}/decision")
def decide(
    item_id: str,
    request: ReviewDecisionRequest,
    db: Annotated[Session, Depends(deps.get_db)],
    current_user: Annotated[User, Depends(deps.get_current_active_user)],
) -> dict[str, Any]:
    _require_reviewer(current_user)
    try:
        return decide_review_item(
            db,
            current_user=current_user,
            item_id=item_id,
            payload=request.model_dump(),
        )
    except Exception:
        db.rollback()
        raise


@router.post("/batch/approve")
def batch_approve(
    request: BatchReviewRequest,
    db: Annotated[Session, Depends(deps.get_db)],
    current_user: Annotated[User, Depends(deps.get_current_active_user)],
) -> dict[str, Any]:
    _require_reviewer(current_user)
    if len(request.item_ids) != len(set(request.item_ids)):
        raise HTTPException(status_code=400, detail="duplicate review item ids")
    items = [
        get_review_item(db, current_user=current_user, item_id=item_id)
        for item_id in request.item_ids
    ]
    signatures = {
        (item["provider"], item["source_type"], item["policy_key"])
        for item in items
    }
    if len(signatures) != 1:
        raise HTTPException(
            status_code=409,
            detail={"code": "batch_policy_mismatch", "message": "batch items must share provider, type, and policy"},
        )
    ineligible = [item["id"] for item in items if not item["batch_eligible"]]
    if ineligible:
        raise HTTPException(
            status_code=409,
            detail={"code": "batch_item_ineligible", "item_ids": ineligible},
        )
    results = []
    try:
        for item in items:
            results.append(
                decide_review_item(
                    db,
                    current_user=current_user,
                    item_id=item["id"],
                    payload={
                        "decision": "approved",
                        "notes": request.notes,
                        "acknowledge_high_risk": False,
                        "acknowledge_low_confidence": False,
                        "conflict_resolutions": {},
                    },
                    commit=False,
                )
            )
        db.commit()
        return {"approved_count": len(results), "results": results}
    except Exception:
        db.rollback()
        raise
