from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.api.v1.api import api_router
from app.middleware.versioning import APIVersionMiddleware, API_VERSIONS
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.ip_whitelist import AdminIPWhitelistMiddleware
from app.middleware.request_logging import RequestLoggingMiddleware
from app.middleware.metrics import PrometheusMiddleware, metrics_endpoint, set_app_info
from app.logging_config import setup_logging

# ── Initialize structured logging ──
setup_logging()


# ── Application Lifespan ──

@asynccontextmanager
async def lifespan(app: FastAPI):
    """啟動 / 關閉鉤子：管理 File Watcher 和排程器生命週期。"""
    # ── Startup ──
    try:
        from app.agent.file_watcher import start_agent_watcher
        start_agent_watcher()
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(f"[Startup] File watcher 啟動失敗（非致命）: {exc}")

    try:
        from app.agent.scheduler import start_agent_scheduler
        start_agent_scheduler()
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(f"[Startup] Scheduler 啟動失敗（非致命）: {exc}")

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
    version="0.9.0",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)

# Set all CORS enabled origins
cors_origins = ["http://localhost:3000", "http://localhost:3001", "http://localhost:3002", "http://localhost:8000"]
if settings.BACKEND_CORS_ORIGINS:
    if isinstance(settings.BACKEND_CORS_ORIGINS, str):
        cors_origins.extend([origin.strip() for origin in settings.BACKEND_CORS_ORIGINS.split(",") if origin.strip()])
    else:
        cors_origins.extend([str(origin) for origin in settings.BACKEND_CORS_ORIGINS])

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    return {"message": "Enclave API", "version": "0.9.0", "docs": "/docs"}

@app.get("/health")
def health_check():
    return {"status": "ok", "env": settings.APP_ENV}

# Prometheus metrics endpoint (T4-11)
app.add_route("/metrics", metrics_endpoint)
set_app_info(version="1.0.0", env=settings.APP_ENV)

@app.get("/api/versions")
def api_versions():
    """Return supported API versions and their status."""
    return API_VERSIONS
