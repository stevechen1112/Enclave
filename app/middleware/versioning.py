"""API version metadata and precise legacy-surface compatibility controls."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, time
from email.utils import format_datetime
from typing import Any

from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.db.session import SessionLocal
from app.models.audit import AuditLog
from app.platform.deprecations import DeprecationSurface, match_api_surface
from app.services.rls import apply_rls_context

logger = logging.getLogger(__name__)


def _apply_deprecation_headers(response: Response, surface: DeprecationSurface) -> None:
    response.headers["Deprecation"] = "true"
    response.headers["Link"] = f'<{surface.replacement_path}>; rel="successor-version"'
    response.headers["X-Enclave-Deprecation-Key"] = surface.key
    response.headers["X-Enclave-Deprecation-Stage"] = surface.stage
    if surface.stage in {"warn", "disable", "remove"}:
        sunset = datetime.combine(surface.eligible_after, time.min, tzinfo=UTC)
        response.headers["Sunset"] = format_datetime(sunset, usegmt=True)
        response.headers["Warning"] = (
            f'299 Enclave "Deprecated API; migrate to {surface.replacement_path}"'
        )


def record_legacy_api_usage(
    *,
    surface: DeprecationSurface,
    user: Any,
    request: Request,
    status_code: int,
    session_factory: Callable[[], Session] = SessionLocal,
) -> bool:
    """Persist one tenant-scoped compatibility event without affecting the request."""
    db = session_factory()
    try:
        apply_rls_context(db, user.tenant_id)
        db.add(
            AuditLog(
                tenant_id=user.tenant_id,
                actor_user_id=user.id,
                action="legacy_surface_used",
                target_type="legacy_surface",
                target_id=surface.key,
                ip_address=request.client.host if request.client else None,
                detail_json={
                    "kind": surface.kind,
                    "legacy_path": surface.legacy_path,
                    "replacement_path": surface.replacement_path,
                    "request_path": request.url.path,
                    "method": request.method,
                    "status_code": status_code,
                },
            )
        )
        db.commit()
        return True
    except Exception:
        db.rollback()
        logger.exception("legacy API telemetry failed", extra={"surface": surface.key})
        return False
    finally:
        db.close()


class APIVersionMiddleware(BaseHTTPMiddleware):
    """Mark only registered legacy APIs; stable v1 APIs are not falsely deprecated."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        surface = match_api_surface(path)
        if surface is not None and surface.is_disabled:
            response: Response = JSONResponse(
                status_code=410,
                content={
                    "detail": "legacy API disabled",
                    "deprecation_key": surface.key,
                    "replacement": surface.replacement_path,
                },
            )
        else:
            response = await call_next(request)

        if path.startswith("/api/v1"):
            response.headers["X-API-Version"] = "v1"
        elif path.startswith("/api/v2"):
            response.headers["X-API-Version"] = "v2"

        if surface is not None:
            _apply_deprecation_headers(response, surface)
            user = getattr(request.state, "current_user", None)
            if user is not None and response.status_code < 500:
                record_legacy_api_usage(
                    surface=surface,
                    user=user,
                    request=request,
                    status_code=response.status_code,
                )
        return response


API_VERSIONS = {
    "versions": [
        {
            "version": "v1",
            "status": "stable",
            "base_url": "/api/v1",
            "deprecation_date": None,
            "sunset_date": None,
            "docs": "/docs",
        },
    ],
    "current": "v1",
    "migration_guide": "/docs/release/MODULAR_PLATFORM_UPGRADE_GUIDE.md",
}
