"""Bound ingestion backlog before accepting more expensive work."""

from __future__ import annotations

import os
import time
from functools import lru_cache
from typing import Any

from redis import Redis
from redis.exceptions import RedisError

from app.config import settings
from app.services.capacity_gate import load_capacity_spec

_UNAVAILABLE_CACHE_UNTIL = 0.0


@lru_cache(maxsize=3)
def _queue_limit(profile_name: str) -> int:
    return int(
        load_capacity_spec()["profiles"][profile_name]["resource_limits"]["queue_depth"]
    )


def _profile_name() -> str:
    name = os.getenv("DEPLOYMENT_PROFILE", os.getenv("CAPACITY_PROFILE", "standard"))
    name = name.strip().lower()
    return name if name in {"lite", "standard", "enterprise"} else "standard"


def check_queue_capacity() -> dict[str, Any]:
    global _UNAVAILABLE_CACHE_UNTIL
    if not settings.QUEUE_GUARD_ENABLED:
        return {"allowed": True, "state": "disabled", "depth": None, "limit": None}
    limit = _queue_limit(_profile_name())
    if time.monotonic() < _UNAVAILABLE_CACHE_UNTIL:
        return {
            "allowed": True,
            "state": "broker_unavailable",
            "depth": None,
            "limit": limit,
        }
    client = None
    try:
        client = Redis.from_url(
            settings.CELERY_BROKER_URL,
            socket_connect_timeout=0.25,
            socket_timeout=0.25,
        )
        depth = int(client.llen("celery") or 0)
    except (RedisError, OSError, ValueError):
        _UNAVAILABLE_CACHE_UNTIL = time.monotonic() + 5
        return {
            "allowed": True,
            "state": "broker_unavailable",
            "depth": None,
            "limit": limit,
        }
    finally:
        if client is not None:
            client.close()
    return {
        "allowed": depth < limit,
        "state": "ready" if depth < limit else "saturated",
        "depth": depth,
        "limit": limit,
    }
