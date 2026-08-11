"""Company form template management — upload DOCX/XLSX, map fields, activate."""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api import deps
from app.models.user import User
from app.services.form_template_service import FormTemplateService

router = APIRouter()


class MappingUpdate(BaseModel):
    field_mapping: Dict[str, str] = Field(default_factory=dict)


class PreviewRequest(BaseModel):
    values: Dict[str, Any] = Field(default_factory=dict)


def _require_admin(user: User) -> None:
    if not (user.is_superuser or user.role in {"owner", "admin"}):
        raise HTTPException(status_code=403, detail="admin required")


def _to_dict(row: Any) -> Dict[str, Any]:
    return {
        "id": str(row.id),
        "form_key": row.form_key,
        "name": row.name,
        "format": row.format,
        "version": row.version,
        "placeholders": row.placeholders or [],
        "field_mapping": row.field_mapping or {},
        "status": row.status,
        "effective_from": row.effective_from.isoformat() if row.effective_from else None,
        "storage_key": row.storage_key,
    }


@router.get("/forms/templates")
def list_templates(
    form_key: Optional[str] = None,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
) -> List[Dict[str, Any]]:
    rows = FormTemplateService(db).list_templates(current_user.tenant_id, form_key=form_key)
    return [_to_dict(r) for r in rows]


@router.post("/forms/templates")
async def upload_template(
    form_key: str = Form(...),
    name: str = Form(""),
    version: str = Form("1.0"),
    file: UploadFile = File(...),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
) -> Dict[str, Any]:
    _require_admin(current_user)
    content = await file.read()
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="file too large")
    try:
        row = FormTemplateService(db).upload(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            form_key=form_key,
            name=name or (file.filename or form_key),
            filename=file.filename or "template.docx",
            content=content,
            version=version,
        )
        db.commit()
        db.refresh(row)
        return _to_dict(row)
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/forms/templates/{template_id}/mapping")
def update_mapping(
    template_id: UUID,
    body: MappingUpdate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
) -> Dict[str, Any]:
    _require_admin(current_user)
    try:
        row = FormTemplateService(db).update_mapping(
            tenant_id=current_user.tenant_id,
            template_id=template_id,
            mapping=body.field_mapping,
        )
        db.commit()
        db.refresh(row)
        return _to_dict(row)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/forms/templates/{template_id}/activate")
def activate_template(
    template_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
) -> Dict[str, Any]:
    _require_admin(current_user)
    try:
        row = FormTemplateService(db).activate(
            tenant_id=current_user.tenant_id, template_id=template_id
        )
        db.commit()
        db.refresh(row)
        return _to_dict(row)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/forms/templates/{template_id}/preview")
def preview_template(
    template_id: UUID,
    body: PreviewRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
):
    try:
        content, filename, media = FormTemplateService(db).preview(
            tenant_id=current_user.tenant_id,
            template_id=template_id,
            values=body.values,
        )
        return Response(
            content=content,
            media_type=media,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
