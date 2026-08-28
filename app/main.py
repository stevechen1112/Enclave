from contextlib import asynccontextmanager
import ipaddress
from pathlib import Path

from dotenv import load_dotenv

# 確保 os.getenv("RAGFLOW_*" 等) 與 pydantic Settings 同源讀取 .env
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

from fastapi import FastAPI, Request, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.config import settings
from app.api.v1.api import api_router
from app.middleware.versioning import APIVersionMiddleware, API_VERSIONS
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.ip_whitelist import AdminIPWhitelistMiddleware
from app.middleware.request_logging import RequestLoggingMiddleware
from app.middleware.metrics import PrometheusMiddleware, metrics_endpoint, set_app_info
from app.middleware.demo_access import DemoAccessMiddleware
from app.logging_config import setup_logging

# ── Initialize structured logging ──
setup_logging()

from app.observability.sentry import init_sentry

init_sentry("enclave-api")


# ── Application Lifespan ──


@asynccontextmanager
async def lifespan(app: FastAPI):
    """啟動 / 關閉鉤子：管理 File Watcher 和排程器生命週期。"""
    # ── Startup ──
    # Enabled sidecars must be safely addressable.  A bad production URL is a
    # configuration error; an unavailable optional sidecar degrades capability
    # truthfully without taking down the canonical Enclave data plane.
    from app.gateway.runtime_health import probe_gateway_runtime
    from app.gateway.sidecar_config import validate_enabled_sidecars

    validate_enabled_sidecars(app_env=settings.APP_ENV)
    await probe_gateway_runtime()

    try:
        from app.services.telemetry import init_telemetry

        init_telemetry("enclave")
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning(f"[Startup] Telemetry init failed: {exc}")

    try:
        from app.agent.file_watcher import start_agent_watcher

        start_agent_watcher()
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning(
            f"[Startup] File watcher 啟動失敗（非致命）: {exc}"
        )

    try:
        from app.agent.scheduler import start_agent_scheduler

        start_agent_scheduler()
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning(
            f"[Startup] Scheduler 啟動失敗（非致命）: {exc}"
        )

    yield

    # ── Shutdown ──
    try:
        from app.agent.file_watcher import stop_agent_watcher

        stop_agent_watcher()
    except Exception:
        pass

    try:
        from app.agent.scheduler import stop_agent_scheduler

        stop_agent_scheduler()
    except Exception:
        pass


app = FastAPI(
    title="Enclave — 企業私有 AI 知識大腦",
    description="地端部署的企業知識庫與 AI 問答平台",
    version="1.0.0",
    openapi_url=(
        f"{settings.API_V1_STR}/openapi.json" if not settings.is_production else None
    ),
    docs_url=("/docs" if not settings.is_production else None),
    redoc_url=("/redoc" if not settings.is_production else None),
    lifespan=lifespan,
)

# Set all CORS enabled origins
cors_origins = [
    "http://localhost:3000",
    "http://localhost:3001",
    "http://localhost:3002",
    "http://localhost:8000",
]
if settings.BACKEND_CORS_ORIGINS:
    if isinstance(settings.BACKEND_CORS_ORIGINS, str):
        cors_origins.extend(
            [
                origin.strip()
                for origin in settings.BACKEND_CORS_ORIGINS.split(",")
                if origin.strip()
            ]
        )
    else:
        cors_origins.extend([str(origin) for origin in settings.BACKEND_CORS_ORIGINS])

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Trust boundary: strip forged X-Enclave-* / X-Service-* from clients
from app.middleware.trust_boundary import TrustBoundaryMiddleware

app.add_middleware(TrustBoundaryMiddleware)

# Passwordless demo administrator sessions may inspect, but never mutate, data.
app.add_middleware(DemoAccessMiddleware)

# API versioning middleware
app.add_middleware(APIVersionMiddleware)

# Admin IP whitelist middleware
app.add_middleware(AdminIPWhitelistMiddleware)

# Request logging middleware
app.add_middleware(RequestLoggingMiddleware)

# Prometheus metrics middleware
app.add_middleware(PrometheusMiddleware)

# Rate limiting middleware
if settings.RATE_LIMIT_ENABLED and not settings.is_development:
    app.add_middleware(RateLimitMiddleware)

# Mount API v1
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/")
def root():
    return {
        "message": "Enclave API",
        "version": "1.0.0",
        "docs": "/docs" if not settings.is_production else None,
    }


@app.get("/health")
def health_check():
    from app.services.release_metadata import get_public_release_metadata
    from app.services.runtime_readiness import database_readiness

    database_ready = database_readiness()
    payload = {
        "status": "ok" if database_ready else "unavailable",
        "env": settings.APP_ENV,
        "dependencies": {"database": "ready" if database_ready else "unavailable"},
        "release": get_public_release_metadata(),
    }
    if not database_ready:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=payload
        )
    return payload


# Prometheus metrics endpoint (T4-11)
@app.get("/metrics", include_in_schema=False)
def metrics(request: Request):
    """Expose metrics only to internal networks in production."""
    if settings.is_production and settings.METRICS_INTERNAL_ONLY:
        client_ip = request.client.host if request.client else ""
        try:
            ip = ipaddress.ip_address(client_ip)
            if not (ip.is_loopback or ip.is_private):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="metrics endpoint is restricted",
                )
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="metrics endpoint is restricted",
            )
    # Refresh the gauge in the same worker serving this scrape. Uvicorn workers
    # do not share in-process Prometheus state, so relying on /health traffic
    # could expose a stale dependency value here.
    from app.services.runtime_readiness import database_readiness
    from app.db.session import refresh_pool_metrics
    from app.services.capacity_metrics import refresh_capacity_runtime_metrics

    database_readiness()
    refresh_pool_metrics()
    refresh_capacity_runtime_metrics()
    return metrics_endpoint(request)


set_app_info(
    version="1.0.0", env=settings.APP_ENV
)  # keep in sync with FastAPI(version=)


@app.get("/api/versions")
def api_versions():
    """Return supported API versions and their status."""
    return API_VERSIONS
