"""
單機／雲端速率限制 Middleware（WS-SECURITY）

地端（development）：IP 級保護即可。
雲端（production／staging）：三層 Redis 滑窗 — IP／user／tenant；
聊天路徑另套用較嚴的 chat_per_user。

Redis 不可用時自動放行，不阻擋正常使用。
"""

from __future__ import annotations

import logging
import os
import time
from typing import ClassVar

import jwt
import redis
from fastapi import Request, status
from jwt import InvalidTokenError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.config import settings
from app.middleware.ip_whitelist import get_client_ip, parse_whitelist

logger = logging.getLogger(__name__)


class RateLimiter:
    """基於 Redis 的滑動視窗限流器"""

    def __init__(self, redis_url: str | None = None):
        if redis_url:
            self._redis_url = redis_url
        elif getattr(settings, "REDIS_HOST", None):
            host = settings.REDIS_HOST
            port = int(getattr(settings, "REDIS_PORT", 6379))
            # production 的 Redis 有密碼（compose 以 REDIS_PASSWORD 注入），
            # 不帶密碼連線會被 NOAUTH 拒絕，限流器退化為常放行
            pwd = os.environ.get("REDIS_PASSWORD", "")
            auth = f":{pwd}@" if pwd else ""
            self._redis_url = f"redis://{auth}{host}:{port}/2"
        else:
            self._redis_url = getattr(
                settings, "CELERY_BROKER_URL", "redis://localhost:6379/2"
            )
        self._redis: redis.Redis | None = None

    @property
    def r(self) -> redis.Redis:
        if self._redis is None:
            self._redis = redis.Redis.from_url(
                self._redis_url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
            self._redis.ping()
        return self._redis

    def is_allowed(
        self,
        key: str,
        max_requests: int,
        window_seconds: int,
    ) -> tuple[bool, int, int]:
        try:
            now = time.time()
            window_start = now - window_seconds
            pipe = self.r.pipeline(transaction=True)
            pipe.zremrangebyscore(key, 0, window_start)
            pipe.zcard(key)
            pipe.zadd(key, {str(now): now})
            pipe.expire(key, window_seconds + 10)
            results = pipe.execute()
            current_count = results[1]

            if current_count >= max_requests:
                self.r.zrem(key, str(now))
                oldest = self.r.zrange(key, 0, 0, withscores=True)
                retry_after = (
                    int(window_seconds - (now - oldest[0][1]))
                    if oldest
                    else window_seconds
                )
                return False, 0, max(retry_after, 1)

            remaining = max_requests - current_count - 1
            return True, max(remaining, 0), 0

        except redis.RedisError as exc:
            logger.warning("Rate limiter Redis error: %s, allowing request", exc)
            return True, max_requests, 0

    def record_abuse(self, key: str, threshold: int = 100, window: int = 60) -> bool:
        abuse_key = f"abuse:{key}"
        try:
            if self.r.get(abuse_key):
                return True

            count_key = f"abuse_count:{key}"
            count = self.r.incr(count_key)
            if count == 1:
                self.r.expire(count_key, window)

            if count > threshold:
                self.r.setex(abuse_key, 600, "1")
                logger.warning("Abuse detected for %s, blocking for 10 minutes", key)
                return True
            return False
        except redis.RedisError as exc:
            logger.warning("Abuse detection error: %s", exc)
            return False


def _cloud_layers_enabled() -> bool:
    return settings.APP_ENV in ("production", "staging", "saas")


def _jwt_subject_and_tenant(request: Request) -> tuple[str | None, str | None]:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None, None
    token = auth[7:].strip()
    if not token:
        return None, None
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        return payload.get("sub"), payload.get("tenant_id")
    except InvalidTokenError:
        return None, None


def _rate_limit_response(
    retry_after: int, *, error: str, message: str, limit: int
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"detail": {"error": error, "message": message}},
        headers={
            "Retry-After": str(retry_after),
            "X-RateLimit-Limit": str(limit),
            "X-RateLimit-Remaining": "0",
        },
    )


class RateLimitMiddleware(BaseHTTPMiddleware):
    SKIP_PATHS: ClassVar[frozenset[str]] = frozenset(
        {
            "/",
            "/health",
            "/api/versions",
            "/docs",
            "/openapi.json",
            "/redoc",
            "/api/v1/documents/supported-formats",
            "/api/v1/payment/notify",
            "/api/v1/auth/login/access-token",
            "/api/v1/sso/",
        }
    )

    def __init__(self, app, redis_url: str | None = None):
        super().__init__(app)
        self.limiter = RateLimiter(redis_url)
        self.trusted_proxies = parse_whitelist(settings.RATE_LIMIT_TRUSTED_PROXY_IPS)

    def _should_skip(self, path: str) -> bool:
        if path in self.SKIP_PATHS:
            return True
        return bool(path.startswith(("/docs", "/api/v1/sso/")))

    async def dispatch(self, request: Request, call_next):
        if not settings.RATE_LIMIT_ENABLED:
            return await call_next(request)

        path = request.url.path
        if self._should_skip(path):
            return await call_next(request)

        client_ip = get_client_ip(request, self.trusted_proxies)

        try:
            if self.limiter.record_abuse(f"ip:{client_ip}"):
                return _rate_limit_response(
                    600,
                    error="abuse_detected",
                    message="偵測到異常行為，暫時封鎖。請稍後再試。",
                    limit=0,
                )

            ip_conf = {
                "max_requests": int(settings.RATE_LIMIT_GLOBAL_PER_IP),
                "window_seconds": 60,
            }
            allowed, _, retry_after = self.limiter.is_allowed(
                f"rl:ip:{client_ip}",
                ip_conf["max_requests"],
                ip_conf["window_seconds"],
            )
            if not allowed:
                return _rate_limit_response(
                    retry_after,
                    error="rate_limited",
                    message="請求過於頻繁，請稍後再試。",
                    limit=ip_conf["max_requests"],
                )

            if _cloud_layers_enabled():
                user_sub, tenant_id = _jwt_subject_and_tenant(request)

                if user_sub:
                    user_conf = {
                        "max_requests": int(settings.RATE_LIMIT_PER_USER),
                        "window_seconds": 60,
                    }
                    allowed, _, retry_after = self.limiter.is_allowed(
                        f"rl:user:{user_sub}",
                        user_conf["max_requests"],
                        user_conf["window_seconds"],
                    )
                    if not allowed:
                        return _rate_limit_response(
                            retry_after,
                            error="rate_limited_user",
                            message="使用者請求過於頻繁，請稍後再試。",
                            limit=user_conf["max_requests"],
                        )

                    if path.startswith("/api/v1/chat"):
                        chat_conf = {
                            "max_requests": int(settings.RATE_LIMIT_CHAT_PER_USER),
                            "window_seconds": 60,
                        }
                        allowed, _, retry_after = self.limiter.is_allowed(
                            f"rl:chat:{user_sub}",
                            chat_conf["max_requests"],
                            chat_conf["window_seconds"],
                        )
                        if not allowed:
                            return _rate_limit_response(
                                retry_after,
                                error="rate_limited_chat",
                                message="聊天請求過於頻繁，請稍後再試。",
                                limit=chat_conf["max_requests"],
                            )

                if tenant_id:
                    tenant_conf = {
                        "max_requests": int(settings.RATE_LIMIT_PER_TENANT),
                        "window_seconds": 60,
                    }
                    allowed, _, retry_after = self.limiter.is_allowed(
                        f"rl:tenant:{tenant_id}",
                        tenant_conf["max_requests"],
                        tenant_conf["window_seconds"],
                    )
                    if not allowed:
                        return _rate_limit_response(
                            retry_after,
                            error="rate_limited_tenant",
                            message="租戶請求過於頻繁，請稍後再試。",
                            limit=tenant_conf["max_requests"],
                        )

        except (redis.RedisError, TypeError, ValueError) as exc:
            logger.warning("Rate-limit middleware degraded open: %s", exc)

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(settings.RATE_LIMIT_GLOBAL_PER_IP)
        return response
