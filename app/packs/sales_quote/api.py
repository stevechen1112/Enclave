"""Sales-quote owned API composition."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api import deps
from app.models.user import User
from app.packs.sales_quote.endpoints import realtime_voice
from app.platform.packs import PackTenantContext


def require_sales_quote_pack_enabled(
    db: Annotated[Session, Depends(deps.get_db)],
    current_user: Annotated[User, Depends(deps.get_current_active_user)],
) -> None:
    from app.composition.packs import build_pack_registry

    if not build_pack_registry().is_enabled_for_tenant(
        "sales_quote",
        context=PackTenantContext(
            tenant_id=current_user.tenant_id,
            db=db,
            module_key="sales_quote",
        ),
    ):
        raise HTTPException(
            status_code=404,
            detail={"code": "module_disabled", "pack_key": "sales_quote"},
        )


router = APIRouter(dependencies=[Depends(require_sales_quote_pack_enabled)])
router.include_router(realtime_voice.router, tags=["voice-realtime"])
