"""Refresh low-cardinality Redis and queue gauges during metrics scrapes."""

from __future__ import annotations

import logging

from redis import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)


def refresh_capacity_runtime_metrics() -> dict[str, float | int | str]:
    from app.config import settings
    from app.observability.business_metrics import set_capacity_runtime_metrics

    ratio = 0.0
    depth = 0
    state = "unavailable"
    client = None
    try:
        client = Redis.from_url(
            settings.CELERY_BROKER_URL,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        info = client.info("memory")
        used = int(info.get("used_memory", 0) or 0)
        maximum = int(info.get("maxmemory", 0) or 0)
        ratio = used / maximum if maximum > 0 else 0.0
        depth = int(client.llen("celery") or 0)
        state = "ready"
    except (RedisError, OSError, ValueError):
        logger.debug("capacity Redis metrics unavailable", exc_info=True)
    finally:
        if client is not None:
            client.close()
    set_capacity_runtime_metrics(redis_memory_ratio=ratio, queue_depth=depth)
    return {"state": state, "redis_memory_ratio": ratio, "queue_depth": depth}
