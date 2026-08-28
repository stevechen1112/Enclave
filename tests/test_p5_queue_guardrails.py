from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.ingestion_guard import enforce_ingestion_queue_capacity
from app.services import queue_guardrails


class _Redis:
    def __init__(self, depth: int):
        self.depth = depth

    def llen(self, _name):
        return self.depth

    def close(self):
        return None


def test_queue_below_profile_limit_is_allowed(monkeypatch):
    queue_guardrails._UNAVAILABLE_CACHE_UNTIL = 0
    monkeypatch.setenv("DEPLOYMENT_PROFILE", "lite")
    monkeypatch.setattr("redis.Redis.from_url", lambda *_args, **_kwargs: _Redis(99))
    result = queue_guardrails.check_queue_capacity()
    assert result == {"allowed": True, "state": "ready", "depth": 99, "limit": 100}


def test_saturated_queue_returns_retryable_503(monkeypatch):
    monkeypatch.setattr(
        "app.api.ingestion_guard.check_queue_capacity",
        lambda: {"allowed": False, "state": "saturated", "depth": 100, "limit": 100},
    )
    with pytest.raises(HTTPException) as raised:
        enforce_ingestion_queue_capacity()
    assert raised.value.status_code == 503
    assert raised.value.detail["error"] == "queue_saturated"
    assert raised.value.headers["Retry-After"] == "30"


def test_broker_unavailable_preserves_durable_ingestion_path(monkeypatch):
    queue_guardrails._UNAVAILABLE_CACHE_UNTIL = 0
    monkeypatch.setattr(
        "redis.Redis.from_url",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("down")),
    )
    result = queue_guardrails.check_queue_capacity()
    assert result["allowed"] is True
    assert result["state"] == "broker_unavailable"
