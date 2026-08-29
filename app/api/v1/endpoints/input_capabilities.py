"""Authenticated, tenant-bound Input capability discovery API."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api import deps
from app.models.user import User
from app.platform.intake import build_input_capability_contract
from app.schemas.input_capabilities import InputCapabilityResponse

router = APIRouter(prefix="/knowledge/input-capabilities", tags=["input-capabilities"])


@router.get("", response_model=InputCapabilityResponse)
def get_input_capabilities(
    current_user: Annotated[User, Depends(deps.get_current_active_user)],
    db: Annotated[Session, Depends(deps.get_db)],
) -> InputCapabilityResponse:
    from app.crud import crud_tenant

    quota = crud_tenant.get_quota_status(db, current_user.tenant_id)
    max_storage_mb = quota.get("max_storage_mb")
    current_storage_mb = float(quota.get("current_storage_mb") or 0)
    max_documents = quota.get("max_documents")
    current_documents = int(quota.get("current_documents") or 0)
    payload = build_input_capability_contract(tenant_id=str(current_user.tenant_id))
    payload["quota"] = {
        "max_documents": max_documents,
        "current_documents": current_documents,
        "remaining_documents": (
            max(0, int(max_documents) - current_documents)
            if max_documents is not None
            else None
        ),
        "max_storage_bytes": (
            int(max_storage_mb) * 1024 * 1024 if max_storage_mb is not None else None
        ),
        "current_storage_bytes": int(current_storage_mb * 1024 * 1024),
        "remaining_storage_bytes": (
            max(0, int((float(max_storage_mb) - current_storage_mb) * 1024 * 1024))
            if max_storage_mb is not None
            else None
        ),
        "warnings": list(quota.get("quota_warnings") or []),
    }
    return InputCapabilityResponse.model_validate(
        payload
    )
