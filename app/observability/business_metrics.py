"""CG-OBS 業務 Prometheus 指標（補充 middleware/metrics.py 的 HTTP 層指標）。"""
from __future__ import annotations

try:
    from prometheus_client import Counter, Histogram

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
    # MKA 營運指標（ENGINEERING_PLAN §13.2／§13.3 SLO）
    MKA_STT_DURATION = Histogram(
        "enclave_mka_stt_duration_seconds",
        "STT provider 呼叫延遲（SLO：p95 ≤8 秒／短語音）",
        ["ok"],  # true|false
        buckets=(0.5, 1, 2, 4, 8, 15, 30, 60),
    )
    MKA_FORM_EXPORT = Counter(
        "enclave_mka_form_export_total",
        "表單匯出結果（未核准匯出於 repository 層阻擋，不計入）",
        ["format", "success"],  # pdf|docx|xlsx|md × true|false
    )
else:
    QUOTA_EXCEEDED = None  # type: ignore[assignment]
    SOURCE_VERIFY_RESULT = None  # type: ignore[assignment]
    MKA_STT_DURATION = None  # type: ignore[assignment]
    MKA_FORM_EXPORT = None  # type: ignore[assignment]


def record_quota_exceeded(axis: str) -> None:
    if PROMETHEUS_AVAILABLE and QUOTA_EXCEEDED is not None:
        QUOTA_EXCEEDED.labels(axis=axis or "unknown").inc()


def record_source_verify_result(*, verified: bool, mode: str) -> None:
    if PROMETHEUS_AVAILABLE and SOURCE_VERIFY_RESULT is not None:
        SOURCE_VERIFY_RESULT.labels(
            mode=mode or "unknown",
            verified="true" if verified else "false",
        ).inc()


def record_mka_stt(*, duration_seconds: float, ok: bool) -> None:
    if PROMETHEUS_AVAILABLE and MKA_STT_DURATION is not None:
        MKA_STT_DURATION.labels(ok="true" if ok else "false").observe(
            max(duration_seconds, 0.0)
        )


def record_mka_form_export(*, format: str, success: bool) -> None:
    if PROMETHEUS_AVAILABLE and MKA_FORM_EXPORT is not None:
        MKA_FORM_EXPORT.labels(
            format=format or "unknown",
            success="true" if success else "false",
        ).inc()
