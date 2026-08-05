"""
P1-2：Fixed Form API endpoint。

GET  /api/v1/forms — 列出可用表單
GET  /api/v1/forms/{name}/schema — 取得表單 schema
POST /api/v1/forms/{name}/validate — 驗證表單值
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from app.api import deps
from app.models.user import User

router = APIRouter()


class ValidateRequest(BaseModel):
    values: Dict[str, Any]


@router.get("/forms")
async def list_forms(
    current_user: User = Depends(deps.get_current_verified_user),
):
    """列出可用表單。"""
    from app.config import settings
    if not settings.FIXED_FORM_ENABLED:
        raise HTTPException(status_code=404, detail="Fixed Form not enabled")

    from app.services.fixed_form import get_form_registry
    registry = get_form_registry()
    forms = registry.list_forms()
    return {"forms": forms}


@router.get("/forms/{form_name}/schema")
async def get_form_schema(
    form_name: str,
    current_user: User = Depends(deps.get_current_verified_user),
):
    """取得表單 schema。"""
    from app.config import settings
    if not settings.FIXED_FORM_ENABLED:
        raise HTTPException(status_code=404, detail="Fixed Form not enabled")

    from app.services.fixed_form import get_form_registry
    registry = get_form_registry()
    schema = registry.get(form_name)
    if schema is None:
        raise HTTPException(status_code=404, detail=f"Form not found: {form_name}")

    return {
        "name": schema.name,
        "version": schema.version,
        "description": schema.description,
        "require_approval": schema.require_approval,
        "approver_roles": schema.approver_roles,
        "fields": [
            {
                "name": f.name,
                "label": f.label,
                "type": f.type.value,
                "required": f.required,
                "options": f.options,
                "min_value": f.min_value,
                "max_value": f.max_value,
                "calculated": f.calculated,
            }
            for f in schema.fields
        ],
    }


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