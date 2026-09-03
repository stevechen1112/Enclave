from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.ingestion_guard import enforce_ingestion_queue_capacity
from app.services import queue_guardrails


class _Redis:
    def __init__(self, depths: dict[str, int]):
        self.depths = depths

    def llen(self, name):
        return self.depths.get(name, 0)

    def close(self):
        return None


def test_queue_below_profile_limit_is_allowed(monkeypatch):
    queue_guardrails._UNAVAILABLE_CACHE_UNTIL = 0
    monkeypatch.setenv("DEPLOYMENT_PROFILE", "lite")
    monkeypatch.setattr(
        "redis.Redis.from_url",
        lambda *_args, **_kwargs: _Redis(
            {"celery": 20, "input.document": 30, "input.media": 49}
        ),
    )
    result = queue_guardrails.check_queue_capacity()
    assert result == {
        "allowed": True,
        "state": "ready",
        "depth": 99,
        "limit": 100,
        "queue_depths": {
            "celery": 20,
            "input.document": 30,
            "input.media": 49,
        },
    }


def test_dedicated_input_queue_counts_toward_saturation(monkeypatch):
    queue_guardrails._UNAVAILABLE_CACHE_UNTIL = 0
    monkeypatch.setenv("DEPLOYMENT_PROFILE", "lite")
    monkeypatch.setattr(
        "redis.Redis.from_url",
        lambda *_args, **_kwargs: _Redis(
            {"celery": 0, "input.document": 1, "input.media": 99}
        ),
    )

    result = queue_guardrails.check_queue_capacity()

    assert result["allowed"] is False
    assert result["state"] == "saturated"
    assert result["depth"] == 100
    assert result["queue_depths"]["input.media"] == 99


def test_saturated_queue_returns_retryable_503(monkeypatch):
    monkeypatch.setattr(
        "app.api.ingestion_guard.check_queue_capacity",
        lambda: {
            "allowed": False,
            "state": "saturated",
            "depth": 100,
            "limit": 100,
            "queue_depths": {"celery": 0, "input.document": 1, "input.media": 99},
        },
    )
    with pytest.raises(HTTPException) as raised:
        enforce_ingestion_queue_capacity()
    assert raised.value.status_code == 503
    assert raised.value.detail["error"] == "queue_saturated"
    assert raised.value.detail["queue_depths"]["input.media"] == 99
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
