from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.media_reliability import (
    MediaCostLimitExceeded,
    MediaCostRates,
    ProviderCircuitBreaker,
    enforce_media_cost_limit,
    estimate_media_cost,
    evaluate_fault_campaign,
    merge_checkpoint,
    provider_circuit_breaker,
)


def test_cost_is_bounded_before_external_work():
    estimate = estimate_media_cost(
        duration_ms=60_000,
        selected_frames=10,
        precision_ratio=0.5,
        rates=MediaCostRates(0.1, 0.2, 0.01, 0.001),
    )
    assert estimate["total_usd"] == 0.31
    with pytest.raises(MediaCostLimitExceeded):
        enforce_media_cost_limit(estimate, maximum_usd=0.30)


def test_checkpoint_cannot_regress_after_worker_retry():
    assert (
        merge_checkpoint({"completed_chunk_index": 2}, {"completed_chunk_index": 3})[
            "completed_chunk_index"
        ]
        == 3
    )
    with pytest.raises(ValueError, match="backwards"):
        merge_checkpoint({"completed_chunk_index": 3}, {"completed_chunk_index": 2})


def test_circuit_breaker_opens_and_half_opens_after_cooldown():
    now = datetime.now(timezone.utc)
    breaker = ProviderCircuitBreaker(failure_threshold=2, cooldown_seconds=30)
    breaker.record_failure(now)
    breaker.record_failure(now)
    assert breaker.allow(now + timedelta(seconds=10)) is False
    assert breaker.allow(now + timedelta(seconds=31)) is True


def test_fault_campaign_rejects_silent_loss_and_missing_faults():
    report = evaluate_fault_campaign(
        [{"fault": "timeout", "accepted": True, "terminal_state": None}],
        {"timeout", "429", "worker_crash"},
    )
    assert report["status"] == "FAIL"
    assert report["silent_loss_count"] == 1
    assert report["missing_faults"] == ["429", "worker_crash"]


def test_provider_breaker_registry_is_shared_per_provider():
    key = f"provider-{datetime.now(timezone.utc).timestamp()}"
    assert provider_circuit_breaker(key) is provider_circuit_breaker(key)
