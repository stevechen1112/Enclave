"""Runtime provider inventory and explicit live probes.

Configuration inspection is read-only and never returns credentials. Live probes are
deliberately opt-in because they call paid/external services; the admin API therefore
exposes them through a POST action rather than running them on every page load.
"""
from __future__ import annotations

import os
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from app.config import settings
from app.services.deployment_mode import resolve_runtime_profiles_no_db


@dataclass(frozen=True)
class ProviderConfiguration:
    role: str
    label: str
    provider: str
    model: str
    enabled: bool
    credential_configured: bool
    required: bool = True


@dataclass(frozen=True)
class ProviderProbeResult:
    role: str
    label: str
    provider: str
    model: str
    status: str
    elapsed_ms: int
    detail: str = ""


_LABELS = {
    "main_llm": "AI 問答",
    "internal_llm": "內容整理與分類",
    "scan_llm": "掃描內容理解",
    "embedding": "知識檢索索引",
    "voice_roundtrip": "語音辨識與語音輸出",
    "long_audio": "長時間錄音與說話者辨識",
    "cloud_ocr": "圖片與掃描文件 OCR",
}


def _credential_configured(provider: str) -> bool:
    key_name = {
        "openai": "OPENAI_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "voyage": "VOYAGE_API_KEY",
        "mistral": "MISTRAL_API_KEY",
    }.get(provider)
    if key_name is None:
        return True
    return bool(getattr(settings, key_name, "") or os.getenv(key_name, ""))


def provider_configuration() -> list[dict[str, Any]]:
    """Return the effective provider map without exposing credential values."""
    profiles = resolve_runtime_profiles_no_db()
    rows: list[ProviderConfiguration] = []
    for profile_name, role in (
        ("main", "main_llm"),
        ("internal", "internal_llm"),
        ("scan", "scan_llm"),
        ("embedding", "embedding"),
    ):
        profile = profiles.get(profile_name, {})
        provider = str(profile.get("provider") or "").lower()
        rows.append(ProviderConfiguration(
            role=role,
            label=_LABELS[role],
            provider=provider,
            model=str(profile.get("model") or ""),
            enabled=True,
            credential_configured=_credential_configured(provider),
        ))

    voice_stt_enabled = bool(settings.VOICE_STT_ENABLED)
    voice_tts_enabled = bool(settings.VOICE_TTS_ENABLED)
    voice_provider = str(settings.VOICE_STT_PROVIDER).lower()
    rows.append(ProviderConfiguration(
        role="voice_roundtrip",
        label=_LABELS["voice_roundtrip"],
        provider=voice_provider,
        model=f"{settings.VOICE_TTS_MODEL} → {settings.VOICE_STT_MODEL}",
        enabled=voice_stt_enabled and voice_tts_enabled,
        credential_configured=_credential_configured(voice_provider),
    ))
    rows.append(ProviderConfiguration(
        role="long_audio",
        label=_LABELS["long_audio"],
        provider=voice_provider,
        model=str(settings.LONG_INTERVIEW_STT_MODEL),
        enabled=voice_stt_enabled,
        credential_configured=_credential_configured(voice_provider),
    ))

    ocr_provider = os.getenv("CLOUD_OCR_PROVIDER", "").strip().lower()
    ocr_model = os.getenv("CLOUD_OCR_MODEL", "").strip()
    rows.append(ProviderConfiguration(
        role="cloud_ocr",
        label=_LABELS["cloud_ocr"],
        provider=ocr_provider or "未設定",
        model=ocr_model,
        enabled=bool(ocr_provider),
        credential_configured=bool(ocr_provider and _credential_configured(ocr_provider)),
    ))
    return [asdict(row) for row in rows]


def _probe_llm(profile_name: str) -> str:
    from app.services.llm_client import LLMClient

    profile = resolve_runtime_profiles_no_db().get(profile_name, {})
    client = LLMClient(
        provider=str(profile.get("provider") or ""),
        model=str(profile.get("model") or "") or None,
        base_url=str(profile.get("base_url") or "") or None,
    )
    return client.complete(
        "你是系統健康檢查。",
        "只回答 PROVIDER_OK。",
        temperature=0,
        # Gemini 3.6 may account for internal reasoning before visible output;
        # a tiny allowance can therefore yield a successful but empty response.
        max_tokens=128,
    )


def _probe_embedding() -> list[float]:
    from app.tasks.document_tasks import embed_texts

    return embed_texts(["企業知識庫 Provider 健康檢查"], input_type="query")[0]


def _probe_voice_roundtrip() -> str:
    from app.services.voice_gateway import _get_stt_provider, _get_tts_provider

    audio = _get_tts_provider().synthesize("語音服務健康檢查八二四六")
    result = _get_stt_provider().transcribe(
        audio,
        language="zh",
        filename="provider-check.mp3",
        content_type="audio/mpeg",
    )
    return result.text


def _probe_long_audio() -> str:
    from app.services.voice_gateway import (
        _get_tts_provider,
        transcribe_long_interview_chunk,
    )

    audio = _get_tts_provider().synthesize("甲：今天確認作業流程。乙：收到，我會完成紀錄。")
    result = transcribe_long_interview_chunk(
        audio,
        filename="long-audio-check.mp3",
        content_type="audio/mpeg",
        language="zh",
    )
    return result.text


def _probe_cloud_ocr() -> str:
    from PIL import Image, ImageDraw
    from app.services.cloud_ocr import transcribe

    handle, filename = tempfile.mkstemp(suffix=".png")
    os.close(handle)
    path = Path(filename)
    try:
        image = Image.new("RGB", (900, 240), "white")
        ImageDraw.Draw(image).text((40, 70), "ENCLAVE OCR CHECK 8246", fill="black")
        image.save(path)
        return transcribe(str(path), "png", max_retries=1).text
    finally:
        path.unlink(missing_ok=True)


def _run_probe(
    config: dict[str, Any],
    probe: Callable[[], Any],
) -> ProviderProbeResult:
    started = time.perf_counter()
    status = "pass"
    detail = "實際呼叫成功"
    try:
        if not config["enabled"]:
            raise RuntimeError("功能未啟用")
        if not config["credential_configured"]:
            raise RuntimeError("必要憑證未設定")
        result = probe()
        if isinstance(result, str) and not result.strip():
            raise RuntimeError("Provider 回傳空白內容")
        if isinstance(result, list) and not result:
            raise RuntimeError("Provider 回傳空白向量")
    except Exception as exc:
        status = "fail"
        safe_messages = {
            "功能未啟用",
            "必要憑證未設定",
            "Provider 回傳空白內容",
            "Provider 回傳空白向量",
        }
        raw = str(exc).splitlines()[0]
        # Never pass provider payloads, URLs, request headers, or credentials to UI.
        detail = raw if raw in safe_messages else f"Provider 呼叫失敗（{exc.__class__.__name__}）"
    return ProviderProbeResult(
        role=config["role"],
        label=config["label"],
        provider=config["provider"],
        model=config["model"],
        status=status,
        elapsed_ms=round((time.perf_counter() - started) * 1000),
        detail=detail,
    )


def probe_required_providers() -> dict[str, Any]:
    """Perform real, non-cached calls for every required production capability."""
    configurations = provider_configuration()
    by_role = {item["role"]: item for item in configurations}
    probes: list[tuple[str, Callable[[], Any]]] = [
        ("main_llm", lambda: _probe_llm("main")),
        ("internal_llm", lambda: _probe_llm("internal")),
        ("scan_llm", lambda: _probe_llm("scan")),
        ("embedding", _probe_embedding),
        ("voice_roundtrip", _probe_voice_roundtrip),
        ("long_audio", _probe_long_audio),
        ("cloud_ocr", _probe_cloud_ocr),
    ]
    results = [asdict(_run_probe(by_role[role], probe)) for role, probe in probes]
    passed = sum(result["status"] == "pass" for result in results)
    return {
        "status": "pass" if passed == len(results) else "fail",
        "passed": passed,
        "total": len(results),
        "results": results,
    }
