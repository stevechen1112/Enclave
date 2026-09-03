"""Stable failure taxonomy for asynchronous Input processing.

Workers must not blindly retry every exception.  This module deliberately uses
small, serialisable dispositions so the same decision can drive persistence,
operator diagnostics and user-facing recovery guidance.
"""

from __future__ import annotations

import signal
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class IngestionFailureDisposition:
    code: str
    category: str
    retryable: bool
    user_message: str
    technical_message: str

    def as_error(self) -> dict[str, object]:
        return {
            "code": self.code,
            "category": self.category,
            "retryable": self.retryable,
            "user_message": self.user_message,
            "message": self.technical_message[:500],
        }


def classify_ingestion_failure(exc: Exception) -> IngestionFailureDisposition:
    """Classify a worker exception without leaking unsafe details to users."""

    code = str(getattr(exc, "code", "") or "").strip()
    retryable = getattr(exc, "retryable", None)
    user_message = str(getattr(exc, "user_message", "") or "").strip()
    technical = str(exc) or exc.__class__.__name__
    if code:
        effective_retryable = bool(retryable) if retryable is not None else False
        return IngestionFailureDisposition(
            code=code,
            category="transient" if effective_retryable else "permanent",
            retryable=effective_retryable,
            user_message=user_message or "來源無法處理，請確認檔案格式後重新上傳。",
            technical_message=technical,
        )

    if isinstance(exc, subprocess.TimeoutExpired):
        return IngestionFailureDisposition(
            code="processing_timeout",
            category="resource",
            retryable=True,
            user_message="處理時間超出限制，系統將自動再次嘗試。",
            technical_message=technical,
        )

    if isinstance(exc, subprocess.CalledProcessError):
        sigkill = int(getattr(signal, "SIGKILL", 9))
        killed = exc.returncode in {
            -sigkill,
            128 + sigkill,
        }
        return IngestionFailureDisposition(
            code="worker_resource_exhausted" if killed else "media_command_failed",
            category="resource" if killed else "transient",
            retryable=True,
            user_message=(
                "媒體處理資源不足，系統將以安全模式再次嘗試。"
                if killed
                else "媒體處理暫時失敗，系統將自動再次嘗試。"
            ),
            technical_message=technical,
        )

    return IngestionFailureDisposition(
        code="processing_failed",
        category="transient",
        retryable=True,
        user_message="處理暫時失敗，系統將自動再次嘗試；若仍失敗請查看問題詳情。",
        technical_message=technical,
    )
