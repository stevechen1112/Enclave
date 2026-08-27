"""MKA-owned API composition preserving existing public URL contracts."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api import deps
from app.api.v1.endpoints import (
    audio_policy,
    enterprise,
    form_templates,
    forms,
    interaction,
    interview,
    job_modules,
    job_roles,
    knowhow,
    knowledge_capture,
    mka_approvals,
    mka_metrics,
    realtime_voice,
    scene,
    scene_admin,
    tasks,
    terms,
)
from app.models.user import User
from app.platform.packs import PackTenantContext


def require_mka_pack_enabled(
    db: Annotated[Session, Depends(deps.get_db)],
    current_user: Annotated[User, Depends(deps.get_current_active_user)],
) -> None:
    from app.composition.packs import build_pack_registry

    registry = build_pack_registry()
    if not registry.is_enabled_for_tenant(
        "mka",
        context=PackTenantContext(tenant_id=current_user.tenant_id, db=db),
    ):
        raise HTTPException(
            status_code=404,
            detail={"code": "module_disabled", "pack_key": "mka"},
        )


router = APIRouter(dependencies=[Depends(require_mka_pack_enabled)])
router.include_router(mka_approvals.router, tags=["mka-approvals"])
router.include_router(knowhow.router, tags=["knowhow"])
router.include_router(forms.router, tags=["forms"])
router.include_router(interaction.router, tags=["interaction"])
router.include_router(scene.router, tags=["scene"])
router.include_router(scene_admin.router, tags=["scene-admin"])
router.include_router(job_modules.router, tags=["job-modules"])
router.include_router(job_roles.router, tags=["job-roles"])
router.include_router(tasks.router, tags=["tasks"])
router.include_router(terms.router, tags=["terms"])
router.include_router(audio_policy.router, tags=["audio-policy"])
router.include_router(form_templates.router, tags=["form-templates"])
router.include_router(enterprise.router, tags=["enterprise"])
router.include_router(mka_metrics.router, tags=["mka-metrics"])
router.include_router(interview.router, tags=["interview"])
router.include_router(knowledge_capture.router, tags=["knowledge-captures"])
router.include_router(realtime_voice.router, tags=["voice-realtime"])
