"""Safety boundary for passwordless demonstration sessions."""

from __future__ import annotations

import re

import jwt
from jwt import InvalidTokenError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import settings

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_AUTH_PATHS = {
    "/api/v1/auth/login/demo",
    "/api/v1/auth/login/access-token",
}

_INTERACTION_PREFIXES = (
    "/api/v1/chat",
    "/api/v1/voice",
    "/api/v1/interaction",
    "/api/v1/voice-realtime",
)
_WORKFLOW_PREFIXES = _INTERACTION_PREFIXES + (
    "/api/v1/tasks",
    "/api/v1/forms",
    "/api/v1/knowhow",
    "/api/v1/interview",
    "/api/v1/knowledge-captures",
    "/api/v1/scene",
    "/api/v1/mka-approvals",
)
_APPROVAL_MUTATION = re.compile(
    r"^/api/v1/approvals/[^/]+/(?:approve|reject|request-changes)$"
)
_KNOWHOW_APPROVAL = re.compile(r"^/api/v1/knowhow/[^/]+/approve$")


def _matches_prefix(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(f"{prefix}/")


def demo_mutation_allowed(path: str, scope: str) -> bool:
    """Allow only resettable, tenant-internal demonstration operations."""
    if scope == "approval":
        can_interact = any(
            _matches_prefix(path, prefix) for prefix in _INTERACTION_PREFIXES
        )
        return can_interact or bool(
            _APPROVAL_MUTATION.fullmatch(path)
            or _KNOWHOW_APPROVAL.fullmatch(path)
        )
    prefixes = (
        _WORKFLOW_PREFIXES
        if scope == "workflow"
        else _INTERACTION_PREFIXES
        if scope == "interaction"
        else ()
    )
    return any(_matches_prefix(path, prefix) for prefix in prefixes)


class DemoAccessMiddleware(BaseHTTPMiddleware):
    """Constrain public Demo tokens to resettable tenant-internal workflows."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.method in _SAFE_METHODS or request.url.path in _AUTH_PATHS:
            return await call_next(request)

        authorization = request.headers.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            return await call_next(request)

        token = authorization.removeprefix("Bearer ").strip()
        try:
            payload = jwt.decode(
                token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
            )
        except InvalidTokenError:
            return await call_next(request)

        if payload.get("demo_mode") is not True:
            return await call_next(request)

        if payload.get("tenant_id") != str(settings.DEMO_TENANT_ID):
            return JSONResponse(
                status_code=403,
                content={"detail": {"error": "invalid_demo_tenant"}},
            )

        scope = str(payload.get("demo_mutation_scope") or "read_only")
        if demo_mutation_allowed(request.url.path, scope):
            return await call_next(request)

        return JSONResponse(
            status_code=403,
            content={
                "detail": {
                    "error": "demo_scope_blocked",
                    "message": (
                        "公開 Demo 只能執行租戶內展示流程；"
                        "不能上傳資料、變更系統設定或呼叫外部整合。"
                    ),
                }
            },
        )
