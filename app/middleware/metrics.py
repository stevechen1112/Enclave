"""
Prometheus Metrics Middleware (T4-11)

Exposes:
  - http_requests_total           (counter)
  - http_request_duration_seconds (histogram)
  - http_requests_in_progress     (gauge)
  - app_info                      (info)
"""

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

try:
    from prometheus_client import (
        Counter,
        Gauge,
        Histogram,
        Info,
        generate_latest,
        CONTENT_TYPE_LATEST,
    )

    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

# ── Metrics ──
if PROMETHEUS_AVAILABLE:
    REQUEST_COUNT = Counter(
        "http_requests_total",
        "Total HTTP requests",
        ["method", "endpoint", "status"],
    )
    REQUEST_DURATION = Histogram(
        "http_request_duration_seconds",
        "Request latency in seconds",
        ["method", "endpoint"],
        buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
    )
    REQUESTS_IN_PROGRESS = Gauge(
        "http_requests_in_progress",
        "Number of in-progress requests",
        ["method"],
    )
    APP_INFO = Info("app", "Application metadata")
    DEPENDENCY_READY = Gauge(
        "enclave_dependency_ready",
        "Whether a required runtime dependency is ready (1) or unavailable (0)",
        ["dependency"],
    )
    DB_POOL_EXHAUSTION = Counter(
        "enclave_db_pool_exhaustion_total",
        "Requests that failed because the SQLAlchemy pool timed out",
    )


def _normalize_path(path: str) -> str:
    """Collapse UUID / numeric path segments to prevent cardinality explosion."""
    import re

    path = re.sub(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        "{id}",
        path,
    )
    path = re.sub(r"/\d+", "/{id}", path)
    return path


class PrometheusMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if not PROMETHEUS_AVAILABLE:
            return await call_next(request)

        method = request.method
        path = _normalize_path(request.url.path)

        # Skip metrics endpoint itself
        if path == "/metrics":
            return await call_next(request)

        REQUESTS_IN_PROGRESS.labels(method=method).inc()
        start = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception as exc:
            REQUEST_COUNT.labels(method=method, endpoint=path, status="500").inc()
            REQUEST_DURATION.labels(method=method, endpoint=path).observe(
                time.perf_counter() - start
            )
            REQUESTS_IN_PROGRESS.labels(method=method).dec()
            try:
                from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

                if isinstance(exc, SQLAlchemyTimeoutError):
                    DB_POOL_EXHAUSTION.inc()
            except Exception:
                pass
            raise

        elapsed = time.perf_counter() - start
        REQUEST_COUNT.labels(
            method=method, endpoint=path, status=str(response.status_code)
        ).inc()
        REQUEST_DURATION.labels(method=method, endpoint=path).observe(elapsed)
        REQUESTS_IN_PROGRESS.labels(method=method).dec()

        return response


def metrics_endpoint(request: Request) -> Response:
    """Expose /metrics for Prometheus scraping."""
    if not PROMETHEUS_AVAILABLE:
        return Response("prometheus_client not installed", status_code=501)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def set_app_info(version: str = "1.0.0", env: str = "development") -> None:
    """Set application info metric."""
    if PROMETHEUS_AVAILABLE:
        APP_INFO.info({"version": version, "environment": env})


def set_dependency_ready(dependency: str, ready: bool) -> None:
    """Publish a low-cardinality dependency state for operational alerts."""
    if PROMETHEUS_AVAILABLE:
        DEPENDENCY_READY.labels(dependency=dependency).set(1 if ready else 0)
