"""
Request Logging Middleware (T4-12)

- Assigns a unique request_id to every request
- Sets tenant_id / user_id context from JWT
- Logs request start & end with timing
"""

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.logging_config import (
    generate_request_id,
    request_id_ctx,
    tenant_id_ctx,
    user_id_ctx,
)

logger = logging.getLogger("enclave.request")


def _extract_user_context(request: Request) -> tuple[str, str]:
    """Try to extract tenant_id and user_id from JWT state (set by auth deps)."""
    # FastAPI auth dependency sets request.state after auth; middleware runs
    # before route handlers, so we parse Authorization header minimally.
    try:
        from app.config import settings
        from jose import jwt

        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
            payload = jwt.decode(
                token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM],
                options={"verify_exp": False},
            )
            return str(payload.get("tenant_id", "-")), str(payload.get("sub", "-"))
    except Exception:
        pass
    return "-", "-"


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        # Generate & set request ID
        rid = generate_request_id()
        request_id_ctx.set(rid)

        # Extract user context from JWT
        tid, uid = _extract_user_context(request)
        tenant_id_ctx.set(tid)
        user_id_ctx.set(uid)

        # Add request ID to response headers
        method = request.method
        path = request.url.path
        client_ip = request.client.host if request.client else "-"

        logger.info("→ %s %s from %s", method, path, client_ip)

        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed = (time.perf_counter() - start) * 1000
            logger.exception("✗ %s %s — %.1fms (unhandled exception)", method, path, elapsed)
            raise

        elapsed = (time.perf_counter() - start) * 1000
        response.headers["X-Request-ID"] = rid

        logger.info(
            "← %s %s — %d — %.1fms",
            method, path, response.status_code, elapsed,
        )
        return response
