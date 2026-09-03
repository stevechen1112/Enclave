"""Authorized, read-only access to out-of-band KQ shadow telemetry."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api import deps
from app.models.document import Document
from app.models.user import User
from app.services.knowledge_decision_shadow import EncryptedAppendOnlyShadowStore

router = APIRouter(prefix="/knowledge/decision-diffs", tags=["knowledge-decision"])


@router.get("")
def list_knowledge_decision_diffs(
    *,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
    limit: int = Query(default=100, ge=1, le=500),
):
    if not current_user.is_superuser and current_user.role not in {
        "owner",
        "admin",
        "auditor",
    }:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要組織管理或稽核權限",
        )

    def source_visible(ref) -> bool:
        raw_id = ref.get("document_id")
        if not raw_id:
            return False
        try:
            document_id = UUID(str(raw_id))
        except ValueError:
            return False
        return (
            db.query(Document.id)
            .filter(
                Document.id == document_id,
                Document.tenant_id == current_user.tenant_id,
                Document.tombstoned_at.is_(None),
                Document.status == "completed",
            )
            .first()
            is not None
        )

    store = EncryptedAppendOnlyShadowStore()
    rows = store.read_for_tenant(
        current_user.tenant_id,
        actor_roles=["admin" if current_user.is_superuser else current_user.role],
        source_authorizer=source_visible,
    )
    return {
        "schema_version": "kq-shadow-view.v1",
        "read_only": True,
        "tenant_id": str(current_user.tenant_id),
        "items": rows[-limit:],
    }
