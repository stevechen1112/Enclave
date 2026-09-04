"""Media-v2 cost, checkpoint and fail-closed reliability controls (AV7)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any


_PROVIDER_BREAKERS: dict[str, "ProviderCircuitBreaker"] = {}


class MediaCostLimitExceeded(RuntimeError):
    retryable = False
    code = "media_cost_limit_exceeded"
    user_message = "此媒體預估處理成本超過目前租戶上限，請縮短內容或聯絡管理員。"


@dataclass(frozen=True)
class MediaCostRates:
    stt_per_minute: float = 0.0
    precision_stt_per_minute: float = 0.0
    vision_per_frame: float = 0.0
    ocr_per_frame: float = 0.0


def estimate_media_cost(
    *,
    duration_ms: int,
    selected_frames: int,
    precision_ratio: float,
    rates: MediaCostRates,
) -> dict[str, float]:
    minutes = max(0, duration_ms) / 60_000
    precision_ratio = min(1.0, max(0.0, precision_ratio))
    items = {
        "stt_usd": minutes * rates.stt_per_minute,
        "precision_stt_usd": minutes * precision_ratio * rates.precision_stt_per_minute,
        "vision_usd": max(0, selected_frames) * rates.vision_per_frame,
        "ocr_usd": max(0, selected_frames) * rates.ocr_per_frame,
    }
    return {
        **{key: round(value, 6) for key, value in items.items()},
        "total_usd": round(sum(items.values()), 6),
    }


def enforce_media_cost_limit(estimate: dict[str, float], *, maximum_usd: float) -> None:
    if maximum_usd < 0 or float(estimate.get("total_usd", 0)) > maximum_usd:
        raise MediaCostLimitExceeded("estimated media processing cost exceeds limit")


def merge_checkpoint(current: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    result = dict(current or {})
    for key, value in update.items():
        if key.endswith("_count") or key.endswith("_index") or key.endswith("_ms"):
            previous = result.get(key)
            if (
                previous is not None
                and isinstance(value, (int, float))
                and value < previous
            ):
                raise ValueError(f"checkpoint cannot move backwards: {key}")
        result[key] = value
    return result


@dataclass
class ProviderCircuitBreaker:
    failure_threshold: int = 3
    cooldown_seconds: int = 60
    failures: list[datetime] = field(default_factory=list)
    opened_at: datetime | None = None

    def allow(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        if self.opened_at is None:
            return True
        if now - self.opened_at >= timedelta(seconds=self.cooldown_seconds):
            self.failures.clear()
            self.opened_at = None
            return True
        return False

    def record_success(self) -> None:
        self.failures.clear()
        self.opened_at = None

    def record_failure(self, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        self.failures.append(now)
        self.failures = [
            item for item in self.failures if now - item <= timedelta(minutes=5)
        ]
        if len(self.failures) >= self.failure_threshold:
            self.opened_at = now


def provider_circuit_breaker(
    provider_key: str, *, failure_threshold: int = 3, cooldown_seconds: int = 60
) -> ProviderCircuitBreaker:
    """Return the process-local breaker used by optional provider passes."""
    if provider_key not in _PROVIDER_BREAKERS:
        _PROVIDER_BREAKERS[provider_key] = ProviderCircuitBreaker(
            failure_threshold=failure_threshold,
            cooldown_seconds=cooldown_seconds,
        )
    return _PROVIDER_BREAKERS[provider_key]


def evaluate_fault_campaign(
    rows: list[dict[str, Any]], required_faults: set[str]
) -> dict[str, Any]:
    observed = {str(row.get("fault")) for row in rows}
    missing = sorted(required_faults - observed)
    silent_loss = [
        row for row in rows if row.get("accepted") and not row.get("terminal_state")
    ]
    duplicates = [
        row for row in rows if int(row.get("unexpected_duplicate_count") or 0) > 0
    ]
    unexplained = [
        row
        for row in rows
        if row.get("terminal_state") == "failed" and not row.get("failure_code")
    ]
    return {
        "status": (
            "PASS"
            if not (missing or silent_loss or duplicates or unexplained)
            else "FAIL"
        ),
        "missing_faults": missing,
        "silent_loss_count": len(silent_loss),
        "unexpected_duplicate_count": sum(
            int(row.get("unexpected_duplicate_count") or 0) for row in duplicates
        ),
        "unexplained_failure_count": len(unexplained),
        "rows": rows,
    }
