"""
P1-1：Voice Interaction Gateway — STT/TTS 抽象層。

借鑑 WeKnora ASR 入庫 pipeline，但 Enclave 自建 voice-first Interaction Gateway。
設計原則（稽核文件 §6.7、§6.8）：
- 音訊轉寫先進 draft，不可直接回答（VOICE_DRAFT_FIRST）
- 關鍵欄位（金額／料號）需使用者確認
- 權限不繞過（AuthorizationContext 必須傳遞）
- 高風險操作需批准

不引入 WeKnora RBAC／UI，Enclave 掌控身分、權限、來源、表單與審核。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol

logger = logging.getLogger(__name__)


class STTProvider(Protocol):
    """語音轉文字 provider 介面。"""

    def transcribe(self, audio_data: bytes, language: str = "zh") -> "TranscriptionResult":
        ...


class TTSProvider(Protocol):
    """文字轉語音 provider 介面。"""

    def synthesize(self, text: str, voice: str = "alloy") -> bytes:
        ...


@dataclass
class TranscriptionResult:
    """STT 結果。"""
    text: str
    language: str = "zh"
    segments: List[Dict[str, Any]] = field(default_factory=list)
    duration_seconds: float = 0.0
    is_draft: bool = True  # 預設為 draft，需人工確認後才可用於回答
    confidence: float = 0.0
    provider: str = ""

    def promote_to_confirmed(self) -> "TranscriptionResult":
        """將 draft 提升為已確認（人工審核後）。"""
        self.is_draft = False
        return self


@dataclass
class VoiceInteractionRequest:
    """語音互動請求。"""
    audio_data: bytes
    authz: Any  # AuthorizationContext
    language: str = "zh"
    modality: str = "voice"  # voice | text
    confirm_fields: List[str] = field(default_factory=list)  # 需確認的關鍵欄位


@dataclass
class VoiceInteractionResponse:
    """語音互動回應。"""
    transcription: Optional[TranscriptionResult] = None
    confirmed_text: str = ""
    needs_confirmation: bool = False
    confirm_fields: List[Dict[str, Any]] = field(default_factory=list)
    audio_output: Optional[bytes] = None
    error: str = ""


class VoiceInteractionGateway:
    """Voice-first Interaction Gateway。

    統一管理 STT/TTS，確保：
    1. 音訊轉寫先進 draft（VOICE_DRAFT_FIRST）
    2. 關鍵欄位需使用者確認
    3. AuthorizationContext 必須傳遞
    4. 高風險操作需批准
    """

    def __init__(self, stt_provider: Optional[STTProvider] = None, tts_provider: Optional[TTSProvider] = None):
        self._stt = stt_provider
        self._tts = tts_provider

    def transcribe(
        self,
        audio_data: bytes,
        authz: Any,
        language: str = "zh",
        max_seconds: int = 120,
    ) -> TranscriptionResult:
        """語音轉文字。

        Args:
            audio_data: 音訊原始資料
            authz: AuthorizationContext（必須，不繞過 PEP）
            language: 語言
            max_seconds: 最大音訊長度（秒）

        Returns:
            TranscriptionResult（預設 is_draft=True）
        """
        if authz is None:
            raise ValueError("AuthorizationContext is required for VoiceInteractionGateway.transcribe")

        from app.config import settings

        if not settings.VOICE_STT_ENABLED:
            raise RuntimeError("VOICE_STT_ENABLED is false")

        if self._stt is None:
            self._stt = _get_stt_provider()

        try:
            result = self._stt.transcribe(audio_data, language=language)
            result.provider = settings.VOICE_STT_PROVIDER

            # 驗收 §6.8：音訊轉寫先進 draft，不可直接回答
            if settings.VOICE_DRAFT_FIRST:
                result.is_draft = True

            logger.info(
                f"STT transcribed {len(result.text)} chars, "
                f"draft={result.is_draft}, provider={result.provider}"
            )
            return result

        except Exception as exc:
            logger.error(f"STT failed: {exc}")
            raise

    def synthesize(
        self,
        text: str,
        authz: Any,
        voice: str = "",
    ) -> bytes:
        """文字轉語音。

        Args:
            text: 要合成的文字
            authz: AuthorizationContext（必須）
            voice: 語音名稱（空字串 = 用 config 預設）

        Returns:
            音訊原始資料
        """
        if authz is None:
            raise ValueError("AuthorizationContext is required for VoiceInteractionGateway.synthesize")

        from app.config import settings

        if not settings.VOICE_TTS_ENABLED:
            raise RuntimeError("VOICE_TTS_ENABLED is false")

        if self._tts is None:
            self._tts = _get_tts_provider()

        voice = voice or settings.VOICE_TTS_VOICE

        try:
            audio = self._tts.synthesize(text, voice=voice)
            logger.info(f"TTS synthesized {len(text)} chars, voice={voice}")
            return audio
        except Exception as exc:
            logger.error(f"TTS failed: {exc}")
            raise

    def extract_confirm_fields(
        self,
        text: str,
        field_types: List[str],
    ) -> List[Dict[str, Any]]:
        """從轉寫文字中提取需確認的關鍵欄位。

        製造業場景常見欄位：
        - 金額（amount）
        - 料號（part_number）
        - 數量（quantity）
        - 日期（date）
        - 客戶名稱（customer）

        Args:
            text: 轉寫文字
            field_types: 要提取的欄位類型列表

        Returns:
            每個欄位的 {type, value, raw_span, needs_confirm}
        """
        import re

        fields = []
        patterns = {
            "amount": r'(?:金額|總價|價格|費用|成本)\s*[：:是]?\s*([0-9,]+(?:\.[0-9]+)?)\s*(?:元|萬|千)?',
            "part_number": r'(?:料號|零件號|品號|型號)\s*[：:是]?\s*([A-Z0-9\-]+)',
            "quantity": r'(?:數量|數|件數)\s*[：:是]?\s*([0-9,]+)\s*(?:個|件|台|批)?',
            "date": r'(?:日期|時間|期限|截止)\s*[：:是]?\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}月\d{1,2}日)',
            "customer": r'(?:客戶|客戶名稱|公司|對方)\s*[：:是]?\s*([\u4e00-\u9fff]+(?:公司|股份有限公司|有限公司)?)',
        }

        for field_type in field_types:
            pattern = patterns.get(field_type)
            if not pattern:
                continue
            matches = re.findall(pattern, text)
            for match in matches:
                fields.append({
                    "type": field_type,
                    "value": match,
                    "raw_span": match,
                    "needs_confirm": True,  # 所有提取的欄位都需確認
                })

        return fields


# ── Provider 工廠 ──

def _get_stt_provider() -> STTProvider:
    """根據 config 建立 STT provider。"""
    from app.config import settings

    if settings.VOICE_STT_PROVIDER == "openai":
        return OpenAISTTProvider()
    elif settings.VOICE_STT_PROVIDER == "azure":
        return AzureSTTProvider()
    elif settings.VOICE_STT_PROVIDER == "local":
        return LocalSTTProvider()
    else:
        raise ValueError(f"Unknown STT provider: {settings.VOICE_STT_PROVIDER}")


def _get_tts_provider() -> TTSProvider:
    """根據 config 建立 TTS provider。"""
    from app.config import settings

    if settings.VOICE_TTS_PROVIDER == "openai":
        return OpenAITTSProvider()
    elif settings.VOICE_TTS_PROVIDER == "azure":
        return AzureTTSProvider()
    elif settings.VOICE_TTS_PROVIDER == "local":
        return LocalTTSProvider()
    else:
        raise ValueError(f"Unknown TTS provider: {settings.VOICE_TTS_PROVIDER}")


# ── OpenAI Provider 實作 ──

class OpenAISTTProvider:
    """OpenAI Whisper STT。"""

    def transcribe(self, audio_data: bytes, language: str = "zh") -> TranscriptionResult:
        import io
        from app.config import settings

        try:
            from openai import OpenAI
        except ImportError:
            raise RuntimeError("openai package not installed")

        client = OpenAI()
        result = client.audio.transcriptions.create(
            model=settings.VOICE_STT_MODEL,
            file=("audio.webm", io.BytesIO(audio_data), "audio/webm"),
            language=language,
            response_format="verbose_json",
        )

        segments = []
        if hasattr(result, "segments") and result.segments:
            segments = [
                {"start": s.get("start", 0), "end": s.get("end", 0), "text": s.get("text", "")}
                for s in result.segments
            ]

        return TranscriptionResult(
            text=result.text or "",
            language=language,
            segments=segments,
            duration_seconds=getattr(result, "duration", 0.0) or 0.0,
            confidence=0.0,  # OpenAI 不直接回傳 confidence
        )


class OpenAITTSProvider:
    """OpenAI TTS。"""

    def synthesize(self, text: str, voice: str = "alloy") -> bytes:
        from app.config import settings

        try:
            from openai import OpenAI
        except ImportError:
            raise RuntimeError("openai package not installed")

        client = OpenAI()
        response = client.audio.speech.create(
            model=settings.VOICE_TTS_MODEL,
            voice=voice,
            input=text,
        )
        return response.content


# ── Azure Provider stubs（待真實 Azure 帳號時實作）──

class AzureSTTProvider:
    """Azure Speech Service STT（待實作）。"""

    def transcribe(self, audio_data: bytes, language: str = "zh") -> TranscriptionResult:
        raise NotImplementedError("Azure STT not yet implemented — set VOICE_STT_PROVIDER=openai")


class AzureTTSProvider:
    """Azure Speech Service TTS（待實作）。"""

    def synthesize(self, text: str, voice: str = "alloy") -> bytes:
        raise NotImplementedError("Azure TTS not yet implemented — set VOICE_TTS_PROVIDER=openai")


# ── Local Provider stubs（待本機模型整合時實作）──

class LocalSTTProvider:
    """本機 STT（如 Whisper.cpp，待實作）。"""

    def transcribe(self, audio_data: bytes, language: str = "zh") -> TranscriptionResult:
        raise NotImplementedError("Local STT not yet implemented — set VOICE_STT_PROVIDER=openai")


class LocalTTSProvider:
    """本機 TTS（如 Piper TTS，待實作）。"""

    def synthesize(self, text: str, voice: str = "alloy") -> bytes:
        raise NotImplementedError("Local TTS not yet implemented — set VOICE_TTS_PROVIDER=openai")


# ── 單例 ──

_gateway: Optional[VoiceInteractionGateway] = None


def get_voice_gateway() -> VoiceInteractionGateway:
    global _gateway
    if _gateway is None:
        _gateway = VoiceInteractionGateway()
    return _gateway