from __future__ import annotations

import subprocess

from app.services.ingestion_failures import classify_ingestion_failure
from app.services.media_productization import MediaPolicyError


def test_media_policy_failure_is_not_retried():
    result = classify_ingestion_failure(
        MediaPolicyError(
            "unsupported audio codec: example",
            code="unsupported_audio_codec",
            user_message="不支援此編碼。",
        )
    )
    assert result.code == "unsupported_audio_codec"
    assert result.category == "permanent"
    assert result.retryable is False
    assert result.user_message == "不支援此編碼。"


def test_timeout_is_resource_failure_and_retryable():
    result = classify_ingestion_failure(
        subprocess.TimeoutExpired(["ffmpeg"], timeout=60)
    )
    assert result.code == "processing_timeout"
    assert result.category == "resource"
    assert result.retryable is True


def test_sigkill_is_resource_failure_and_retryable():
    result = classify_ingestion_failure(
        subprocess.CalledProcessError(-9, ["ffmpeg"])
    )
    assert result.code == "worker_resource_exhausted"
    assert result.category == "resource"
    assert result.retryable is True
