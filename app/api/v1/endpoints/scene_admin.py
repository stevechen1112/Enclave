"""MKA Scene Registry admin API — CRUD for opaque QR tokens."""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api import deps
from app.models.mka import SceneRegistry
from app.models.user import User

router = APIRouter()


class SceneUpsertRequest(BaseModel):
    token: str = Field(..., min_length=1, max_length=200)
    label: Optional[str] = None
    site_id: Optional[str] = None
    plant_id: Optional[str] = None
    line_id: Optional[str] = None
    equipment_id: Optional[str] = None
    equipment_model: Optional[str] = None
    work_order_id: Optional[str] = None
    product_id: Optional[str] = None
    part_number: Optional[str] = None
    customer_id: Optional[str] = None
    document_version_scope: Optional[str] = None
    active: bool = True


def _to_dict(row: SceneRegistry) -> Dict[str, Any]:
    return {
        "id": str(row.id),
        "tenant_id": str(row.tenant_id),
        "token": row.token,
        "label": row.label,
        "site_id": row.site_id,
        "plant_id": row.plant_id,
        "line_id": row.line_id,
        "equipment_id": row.equipment_id,
        "equipment_model": row.equipment_model,
        "work_order_id": row.work_order_id,
        "product_id": row.product_id,
        "part_number": row.part_number,
        "customer_id": row.customer_id,
        "document_version_scope": row.document_version_scope,
        "active": row.active,
    }


def _require_admin(user: User) -> None:
    if not (user.is_superuser or user.role in {"owner", "admin"}):
        raise HTTPException(status_code=403, detail="admin required")


@router.get("/scene/registry")
def list_scenes(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
) -> List[Dict[str, Any]]:
    _require_admin(current_user)
    rows = (
        db.query(SceneRegistry)
        .filter(SceneRegistry.tenant_id == current_user.tenant_id)
        .order_by(SceneRegistry.created_at.desc())
        .limit(500)
        .all()
    )
    return [_to_dict(r) for r in rows]


@router.post("/scene/registry")
def create_scene(
    body: SceneUpsertRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
) -> Dict[str, Any]:
    _require_admin(current_user)
    token = body.token.strip()
    if "\n" in token or "\r" in token:
        raise HTTPException(status_code=400, detail="invalid token")
    exists = (
        db.query(SceneRegistry)
        .filter(
            SceneRegistry.tenant_id == current_user.tenant_id,
            SceneRegistry.token == token,
        )
        .first()
    )
    if exists:
        raise HTTPException(status_code=409, detail="token already exists")
    row = SceneRegistry(
        tenant_id=current_user.tenant_id,
        token=token,
        created_by=current_user.id,
        **body.model_dump(exclude={"token"}),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_dict(row)


@router.patch("/scene/registry/{scene_id}")
def update_scene(
    scene_id: UUID,
    body: SceneUpsertRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
) -> Dict[str, Any]:
    _require_admin(current_user)
    row = (
        db.query(SceneRegistry)
        .filter(
            SceneRegistry.id == scene_id,
            SceneRegistry.tenant_id == current_user.tenant_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="scene not found")
    data = body.model_dump()
    token = data.pop("token").strip()
    if "\n" in token or "\r" in token:
        raise HTTPException(status_code=400, detail="invalid token")
    conflict = (
        db.query(SceneRegistry)
        .filter(
            SceneRegistry.tenant_id == current_user.tenant_id,
            SceneRegistry.token == token,
            SceneRegistry.id != scene_id,
        )
        .first()
    )
    if conflict:
        raise HTTPException(status_code=409, detail="token already exists")
    row.token = token
    for key, value in data.items():
        setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return _to_dict(row)


@router.delete("/scene/registry/{scene_id}")
def deactivate_scene(
    scene_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
) -> Dict[str, Any]:
    _require_admin(current_user)
    row = (
        db.query(SceneRegistry)
        .filter(
            SceneRegistry.id == scene_id,
            SceneRegistry.tenant_id == current_user.tenant_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="scene not found")
    row.active = False
    db.commit()
    return {"id": str(row.id), "active": False}
