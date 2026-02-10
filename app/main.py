from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.api.v1.api import api_router
from app.api.v2.api import api_v2_router
from app.middleware.versioning import APIVersionMiddleware, API_VERSIONS
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.ip_whitelist import AdminIPWhitelistMiddleware
from app.middleware.request_logging import RequestLoggingMiddleware
from app.middleware.metrics import PrometheusMiddleware, metrics_endpoint, set_app_info
from app.middleware.custom_domain import CustomDomainMiddleware
from app.logging_config import setup_logging

# ── Initialize structured logging ──
setup_logging()

app = FastAPI(
    title=settings.APP_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
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

# API versioning middleware – adds deprecation headers to v1 responses
app.add_middleware(APIVersionMiddleware)

# Admin API IP whitelist (T4-4) – blocks non-whitelisted IPs from admin endpoints
app.add_middleware(AdminIPWhitelistMiddleware)

# Request logging middleware (T4-12) – request ID, timing, context
app.add_middleware(RequestLoggingMiddleware)

# Prometheus metrics middleware (T4-11) – request count, latency, in-progress
app.add_middleware(PrometheusMiddleware)

# Custom domain resolution middleware (T4-6) – resolves tenant from Host header
app.add_middleware(CustomDomainMiddleware)

# Rate limiting middleware (only in non-development or when explicitly enabled)
if settings.RATE_LIMIT_ENABLED and not settings.is_development:
    app.add_middleware(RateLimitMiddleware)

# Mount API v1 & v2
app.include_router(api_router, prefix=settings.API_V1_STR)
app.include_router(api_v2_router, prefix="/api/v2")

@app.get("/")
def root():
    return {"message": "Welcome to UniHR SaaS API", "docs": "/docs"}

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
