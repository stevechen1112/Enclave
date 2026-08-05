"""Fixed Form API, including tenant-scoped persistent form instances."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Any, Dict, Optional
from sqlalchemy.orm import Session

from app.api import deps
from app.models.user import User
from app.services.mka_persistence import (
    MKAConflictError,
    MKAForbiddenError,
    MKANotFoundError,
    MKARepository,
    form_definition_to_dict,
    form_instance_to_dict,
    approval_to_dict,
)

router = APIRouter()


class ValidateRequest(BaseModel):
    values: Dict[str, Any]


class FormCreateRequest(BaseModel):
    values: Dict[str, Any] = Field(default_factory=dict)
    provenance: Dict[str, Any] = Field(default_factory=dict)
    module_key: Optional[str] = None


class FormPatchRequest(BaseModel):
    record_version: int
    values: Dict[str, Any]
    provenance: Dict[str, Any] = Field(default_factory=dict)


class VersionRequest(BaseModel):
    record_version: int


class FormSubmitRequest(VersionRequest):
    idempotency_key: str


def _raise_mka(exc: Exception) -> None:
    if isinstance(exc, MKANotFoundError):
        raise HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, MKAForbiddenError):
        raise HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, MKAConflictError):
        raise HTTPException(status_code=409, detail=str(exc))
    raise HTTPException(status_code=400, detail=str(exc))


def _actor_kwargs(user: User) -> Dict[str, Any]:
    """Endpoint-layer actor context; repository performs authoritative check."""
    return {
        "actor_id": user.id,
        "actor_roles": [user.role],
        "is_superuser": bool(user.is_superuser),
    }


@router.get("/forms")
async def list_forms(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
):
    """列出目前租戶的 active 表單；第一次讀取時 lazy seed。"""
    from app.config import settings
    if not settings.FIXED_FORM_ENABLED:
        raise HTTPException(status_code=404, detail="Fixed Form not enabled")
    rows = MKARepository(db).list_form_definitions(tenant_id=current_user.tenant_id)
    db.commit()
    return {
        "forms": [row.form_key for row in rows],
        "definitions": [form_definition_to_dict(row) for row in rows],
    }


@router.get("/forms/{form_name}/schema")
async def get_form_schema(
    form_name: str,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
):
    """取得租戶擁有的表單 schema。"""
    from app.config import settings
    if not settings.FIXED_FORM_ENABLED:
        raise HTTPException(status_code=404, detail="Fixed Form not enabled")
    try:
        row = MKARepository(db).get_form_definition(
            tenant_id=current_user.tenant_id, form_key=form_name
        )
        db.commit()
        payload = form_definition_to_dict(row)
        payload.update(row.json_schema or {})
        return payload
    except Exception as exc:
        db.rollback()
        _raise_mka(exc)


@router.post("/forms/{form_name}/validate")
async def validate_form(
    form_name: str,
    request: ValidateRequest,
    current_user: User = Depends(deps.get_current_verified_user),
):
    """驗證表單值。"""
    from app.config import settings
    if not settings.FIXED_FORM_ENABLED:
        raise HTTPException(status_code=404, detail="Fixed Form not enabled")

    from app.services.fixed_form import get_form_registry, FixedFormValidator
    registry = get_form_registry()
    schema = registry.get(form_name)
    if schema is None:
        raise HTTPException(status_code=404, detail=f"Form not found: {form_name}")

    errors = FixedFormValidator.validate(schema, request.values)
    return {
        "valid": len(errors) == 0,
        "errors": errors,
    }


@router.post("/forms/{form_name}/instances")
def create_form_instance(
    form_name: str,
    request: FormCreateRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
):
    try:
        row = MKARepository(db).create_form_instance(
            tenant_id=current_user.tenant_id,
            owner_id=current_user.id,
            form_key=form_name,
            values=request.values,
            provenance=request.provenance,
            module_key=request.module_key,
        )
        db.commit()
        db.refresh(row)
        return form_instance_to_dict(row)
    except Exception as exc:
        db.rollback()
        _raise_mka(exc)


@router.get("/forms/instances/{instance_id}")
def get_form_instance(
    instance_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
):
    try:
        row = MKARepository(db).get_form_instance(
            tenant_id=current_user.tenant_id,
            instance_id=instance_id,
            **_actor_kwargs(current_user),
        )
        return form_instance_to_dict(row)
    except Exception as exc:
        _raise_mka(exc)


@router.patch("/forms/instances/{instance_id}")
def patch_form_instance(
    instance_id: UUID,
    request: FormPatchRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
):
    try:
        row = MKARepository(db).patch_form_instance(
            tenant_id=current_user.tenant_id,
            instance_id=instance_id,
            **_actor_kwargs(current_user),
            expected_version=request.record_version,
            values=request.values,
            provenance=request.provenance,
        )
        db.commit()
        db.refresh(row)
        return form_instance_to_dict(row)
    except Exception as exc:
        db.rollback()
        _raise_mka(exc)


@router.post("/forms/instances/{instance_id}/calculate")
def calculate_form_instance(
    instance_id: UUID,
    request: VersionRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
):
    try:
        row = MKARepository(db).calculate_form(
            tenant_id=current_user.tenant_id,
            instance_id=instance_id,
            **_actor_kwargs(current_user),
            expected_version=request.record_version,
        )
        db.commit()
        db.refresh(row)
        return form_instance_to_dict(row)
    except Exception as exc:
        db.rollback()
        _raise_mka(exc)


@router.post("/forms/instances/{instance_id}/validate")
def validate_form_instance(
    instance_id: UUID,
    request: VersionRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
):
    try:
        row = MKARepository(db).validate_form(
            tenant_id=current_user.tenant_id,
            instance_id=instance_id,
            **_actor_kwargs(current_user),
            expected_version=request.record_version,
        )
        db.commit()
        db.refresh(row)
        return form_instance_to_dict(row)
    except Exception as exc:
        db.rollback()
        _raise_mka(exc)


@router.post("/forms/instances/{instance_id}/submit")
def submit_form_instance(
    instance_id: UUID,
    request: FormSubmitRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
):
    try:
        row, approval = MKARepository(db).submit_form(
            tenant_id=current_user.tenant_id,
            instance_id=instance_id,
            submitted_by=current_user.id,
            expected_version=request.record_version,
            idempotency_key=request.idempotency_key,
        )
        db.commit()
        db.refresh(row)
        db.refresh(approval)
        return {
            "form": form_instance_to_dict(row),
            "approval": approval_to_dict(approval),
        }
    except Exception as exc:
        db.rollback()
        _raise_mka(exc)