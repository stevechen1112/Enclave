"""Training/know-how owned API composition."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api import deps
from app.api.v1.endpoints import audio_policy, interview, knowhow, realtime_voice
from app.models.user import User
from app.platform.packs import PackTenantContext


def require_training_pack_enabled(
    db: Annotated[Session, Depends(deps.get_db)],
    current_user: Annotated[User, Depends(deps.get_current_active_user)],
) -> None:
    from app.composition.packs import build_pack_registry

    if not build_pack_registry().is_enabled_for_tenant(
        "training_knowhow",
        context=PackTenantContext(
            tenant_id=current_user.tenant_id,
            db=db,
            module_key="training_knowhow",
        ),
    ):
        raise HTTPException(
            status_code=404,
            detail={"code": "module_disabled", "pack_key": "training_knowhow"},
        )


router = APIRouter(dependencies=[Depends(require_training_pack_enabled)])
router.include_router(knowhow.router, tags=["knowhow"])
router.include_router(interview.router, tags=["interview"])
router.include_router(realtime_voice.router, tags=["voice-realtime"])
router.include_router(audio_policy.router, tags=["audio-policy"])
