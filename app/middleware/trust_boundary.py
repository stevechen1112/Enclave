"""
Phase 0/1 — Edge trust boundary middleware.

不信任外部傳入的 X-Enclave-* header：Edge 必須移除，
Gateway 只接受內部重簽的短效 service token。
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp


# 外部不可信任、必須剝離的標頭前綴
_STRIP_PREFIXES = (
    "x-enclave-",
    "x-service-",
)


class TrustBoundaryMiddleware(BaseHTTPMiddleware):
    """剝離客戶端偽造的 Enclave / service 內部標頭。"""

    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        # 重建 headers，移除不信任前綴
        headers = [
            (k, v)
            for k, v in request.scope.get("headers", [])
            if not k.decode("latin-1").lower().startswith(_STRIP_PREFIXES)
        ]
        request.scope["headers"] = headers
        return await call_next(request)
