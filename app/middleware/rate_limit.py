"""
單機資源保護 Middleware（P9-8）

地端版本不需要三層租戶速率限制。
改為簡單的單機保護：
  - 同一 IP 每分鐘最多 N 次請求（防止本機腳本失控）
  - Redis 不可用時自動放行（不阻擋正常使用）
"""
import logging
import time
from typing import Optional, Tuple

import redis
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.config import settings

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════
#  Rate Limiter Core
# ═══════════════════════════════════════════

class RateLimiter:
    """基於 Redis 的滑動視窗限流器"""

    def __init__(self, redis_url: Optional[str] = None):
        self._redis_url = redis_url or getattr(settings, "CELERY_BROKER_URL", "redis://localhost:6379/0")
        self._redis: Optional[redis.Redis] = None

    @property
    def r(self) -> redis.Redis:
        if self._redis is None:
            try:
                self._redis = redis.Redis.from_url(
                    self._redis_url,
                    decode_responses=True,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                )
                self._redis.ping()
            except Exception:
                self._redis = None
                raise
        return self._redis

    def is_allowed(
        self,
        key: str,
        max_requests: int,
        window_seconds: int,
    ) -> Tuple[bool, int, int]:
        """
        滑動視窗限流檢查。
        回傳 (allowed, remaining, retry_after_seconds)
        """
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
                # 超過限制 — 移除剛加的
                self.r.zrem(key, str(now))
                # 計算下次可用時間
                oldest = self.r.zrange(key, 0, 0, withscores=True)
                retry_after = int(window_seconds - (now - oldest[0][1])) if oldest else window_seconds
                return False, 0, max(retry_after, 1)

            remaining = max_requests - current_count - 1
            return True, max(remaining, 0), 0

        except Exception as e:
            logger.warning("Rate limiter Redis error: %s, allowing request", e)
            return True, max_requests, 0  # Redis 不可用時放行

    def record_abuse(self, key: str, threshold: int = 100, window: int = 60) -> bool:
        """
        濫用偵測：如果短時間內超過閾值，標記為濫用。
        回傳 True 表示已被標記為濫用。
        """
        abuse_key = f"abuse:{key}"
        try:
            blocked = self.r.get(abuse_key)
            if blocked:
                return True

            count_key = f"abuse_count:{key}"
            count = self.r.incr(count_key)
            if count == 1:
                self.r.expire(count_key, window)

            if count > threshold:
                # 封鎖 10 分鐘
                self.r.setex(abuse_key, 600, "1")
                logger.warning("Abuse detected for %s, blocking for 10 minutes", key)
                return True

            return False
        except Exception as e:
            logger.warning("Abuse detection error: %s", e)
            return False


# ═══════════════════════════════════════════
#  Rate Limit Configuration
# ═══════════════════════════════════════════

# 單機保護設定：同一 IP 每分鐘最多 200 次（地端通常只有少數使用者）
RATE_LIMITS = {
    "global_per_ip": {
        "max_requests": int(getattr(settings, "RATE_LIMIT_GLOBAL_PER_IP", 200)),
        "window_seconds": 60,
    },
    "chat_per_user": {
        "max_requests": int(getattr(settings, "RATE_LIMIT_CHAT_PER_USER", 30)),
        "window_seconds": 60,
    },
}


# ═══════════════════════════════════════════
#  FastAPI Middleware
# ═══════════════════════════════════════════

class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    單機資源保護 Middleware（P9-8）。
    依序檢查：
    1. IP 是否被濫用封鎖（短時間大量請求）
    2. IP 級全域限流（每分鐘上限）
    Redis 不可用時自動放行，不阻礙正常使用。
    """

    SKIP_PATHS = {"/", "/health", "/api/versions", "/docs", "/openapi.json", "/redoc",
                   "/api/v1/documents/supported-formats"}

    def __init__(self, app, redis_url: Optional[str] = None):
        super().__init__(app)
        self.limiter = RateLimiter(redis_url)

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # 跳過健康檢查等端點
        if path in self.SKIP_PATHS or path.startswith("/docs"):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"

        try:
            # 1. 濫用檢查
            if self.limiter.record_abuse(f"ip:{client_ip}"):
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={
                        "detail": {
                            "error": "abuse_detected",
                            "message": "偵測到異常行為，暫時封鎖。請稍後再試。",
                        }
                    },
                    headers={"Retry-After": "600"},
                )

            # 2. IP 級全域限流
            ip_conf = RATE_LIMITS["global_per_ip"]
            allowed, remaining, retry_after = self.limiter.is_allowed(
                f"rl:ip:{client_ip}",
                ip_conf["max_requests"],
                ip_conf["window_seconds"],
            )
            if not allowed:
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={
                        "detail": {
                            "error": "rate_limited",
                            "message": "請求過於頻繁，請稍後再試。",
                        }
                    },
                    headers={
                        "Retry-After": str(retry_after),
                        "X-RateLimit-Limit": str(ip_conf["max_requests"]),
                        "X-RateLimit-Remaining": "0",
                    },
                )

        except Exception:
            # Redis 不可用時不阻擋請求
            pass

        response = await call_next(request)

        # 添加限流標頭
        try:
            response.headers["X-RateLimit-Limit"] = str(RATE_LIMITS["global_per_ip"]["max_requests"])
        except Exception:
            pass

        return response
