"""API versioning middleware.

Adds deprecation headers to v1 responses and provides
version info via a dedicated endpoint.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Configurable deprecation date (set to empty string to disable)
V1_DEPRECATION_DATE = ""  # e.g. "2026-12-31"
V1_SUNSET_DATE = ""       # e.g. "2027-06-30"


class APIVersionMiddleware(BaseHTTPMiddleware):
    """Adds Deprecation / Sunset headers to /api/v1 responses."""

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)

        path = request.url.path
        if path.startswith("/api/v1"):
            if V1_DEPRECATION_DATE:
                response.headers["Deprecation"] = V1_DEPRECATION_DATE
            if V1_SUNSET_DATE:
                response.headers["Sunset"] = V1_SUNSET_DATE
            response.headers["X-API-Version"] = "v1"
            response.headers["X-API-Upgrade"] = (
                "This API version will be deprecated. "
                "Please migrate to /api/v2. "
                "See /api/versions for details."
            )
        elif path.startswith("/api/v2"):
            response.headers["X-API-Version"] = "v2"

        return response


# ─── Version info endpoint data ───

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
    "migration_guide": None,
}
