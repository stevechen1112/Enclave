"""
MKA Scene API — §5.3。

POST /scene/resolve — qr_token/barcode → 驗證 → 回 SceneContext
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.api import deps
from app.models.user import User

router = APIRouter()


class SceneResolveRequest(BaseModel):
    qr_token: Optional[str] = None
    barcode: Optional[str] = None


@router.post("/scene/resolve")
def resolve_scene(
    request: SceneResolveRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
):
    """QR token / barcode → 驗證 → 回 SceneContext（§5.3）。

    禁止直接把掃描字串拼入 prompt。
    """
    if not request.qr_token and not request.barcode:
        raise HTTPException(status_code=400, detail="qr_token or barcode required")

    from app.services.scene_resolver import SceneResolver

    resolver = SceneResolver(db=db, tenant_id=current_user.tenant_id)
    scene = resolver.resolve(
        qr_token=request.qr_token or "",
        barcode=request.barcode or "",
    )

    if scene is None:
        raise HTTPException(status_code=404, detail="Scene could not be resolved")

    return scene.to_dict()