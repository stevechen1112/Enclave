"""CG-OBS 業務 Prometheus 指標（補充 middleware/metrics.py 的 HTTP 層指標）。"""
from __future__ import annotations

try:
    from prometheus_client import Counter

    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

if PROMETHEUS_AVAILABLE:
    QUOTA_EXCEEDED = Counter(
        "enclave_quota_exceeded_total",
        "配額超限次數（429）",
        ["axis"],  # query, token, storage, document, user
    )
    SOURCE_VERIFY_RESULT = Counter(
        "enclave_source_verify_total",
        "source_verification 稽核結果",
        ["mode", "verified"],  # verified: true|false
    )
else:
    QUOTA_EXCEEDED = None  # type: ignore[assignment]
    SOURCE_VERIFY_RESULT = None  # type: ignore[assignment]


def record_quota_exceeded(axis: str) -> None:
    if PROMETHEUS_AVAILABLE and QUOTA_EXCEEDED is not None:
        QUOTA_EXCEEDED.labels(axis=axis or "unknown").inc()


def record_source_verify_result(*, verified: bool, mode: str) -> None:
    if PROMETHEUS_AVAILABLE and SOURCE_VERIFY_RESULT is not None:
        SOURCE_VERIFY_RESULT.labels(
            mode=mode or "unknown",
            verified="true" if verified else "false",
        ).inc()
