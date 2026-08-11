"""Enterprise integration API — adapter contracts + guarded writes."""
from __future__ import annotations

from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api import deps
from app.models.user import User
from app.services.enterprise_adapters import get_adapter, list_adapter_contracts
from app.services.write_guardrail import WriteRequest, WriteRisk, get_write_guardrail

router = APIRouter()


class PrefillRequest(BaseModel):
    form_key: str
    context: Dict[str, Any] = Field(default_factory=dict)


class WriteBody(BaseModel):
    target_system: str
    operation: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    risk: str = "low_risk_write"
    approval_token: Optional[str] = None
    idempotency_key: Optional[str] = None


@router.get("/enterprise/adapters")
def adapters_contract(
    current_user: User = Depends(deps.get_current_verified_user),
) -> Dict[str, Any]:
    return {
        "adapters": list_adapter_contracts(),
        "note": "真實客戶系統規格／憑證為外部 gate，未配置時 fail-closed",
    }


@router.get("/enterprise/{system}/health")
def adapter_health(
    system: str,
    current_user: User = Depends(deps.get_current_verified_user),
) -> Dict[str, Any]:
    try:
        return get_adapter(system, configured=False).health()
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/enterprise/{system}/prefill")
def adapter_prefill(
    system: str,
    body: PrefillRequest,
    current_user: User = Depends(deps.get_current_verified_user),
) -> Dict[str, Any]:
    try:
        return get_adapter(system, configured=False).prefill(body.form_key, body.context)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/enterprise/writes")
def guarded_write(
    body: WriteBody,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
) -> Dict[str, Any]:
    if not (current_user.is_superuser or current_user.role in {"owner", "admin"}):
        raise HTTPException(status_code=403, detail="admin required")
    try:
        risk = WriteRisk(body.risk)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid risk") from exc

    adapter = get_adapter(body.target_system, configured=False)
    req = WriteRequest(
        target_system=body.target_system,
        operation=body.operation,
        risk=risk,
        payload=body.payload,
        approval_token=body.approval_token or "",
        idempotency_key=body.idempotency_key or "",
        initiated_by=str(current_user.id),
        tenant_id=str(current_user.tenant_id),
        approval_required=risk in {WriteRisk.HIGH_RISK_WRITE, WriteRisk.LOW_RISK_WRITE},
    )
    guard = get_write_guardrail(db=db, tenant_id=current_user.tenant_id)

    def _exec(payload: Dict[str, Any]) -> Dict[str, Any]:
        return adapter.write(body.operation, payload)

    result = guard.execute(req, _exec)
    db.commit()
    return result.to_dict()


@router.get("/enterprise/writes/audit")
def write_audit(
    correlation_id: Optional[str] = None,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
) -> Dict[str, Any]:
    if not (current_user.is_superuser or current_user.role in {"owner", "admin"}):
        raise HTTPException(status_code=403, detail="admin required")
    guard = get_write_guardrail(db=db, tenant_id=current_user.tenant_id)
    return {"events": guard.get_audit_log(correlation_id)}
