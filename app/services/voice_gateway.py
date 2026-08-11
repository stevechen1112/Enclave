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


_CN_DIGIT = {
    "零": 0, "一": 1, "二": 2, "兩": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}
_CN_UNIT = {"十": 10, "百": 100, "千": 1000}


def _cn_to_number(text: str) -> Optional[int]:
    """中文數字（萬以下）轉整數；不支援的字元回傳 None。

    支援口語省略寫法：一百二 → 120、三千五 → 3500（末位數字乘上
    最後出現單位的十分之一）。
    """
    section = 0
    number = 0
    last_unit = 0
    for ch in text:
        if ch in _CN_DIGIT:
            number = _CN_DIGIT[ch]
        elif ch in _CN_UNIT:
            unit = _CN_UNIT[ch]
            section += (number or 1) * unit
            number = 0
            last_unit = unit
        else:
            return None
    if number and last_unit >= 100:
        # 口語省略：「一百二」的「二」代表二十
        section += number * (last_unit // 10)
    else:
        section += number
    return section or None


def _normalize_number(raw: str) -> Optional[str]:
    """抽取到的數字字串正規化：阿拉伯數字去逗號；中文數字轉阿拉伯。"""
    if any(ch in _CN_DIGIT or ch in _CN_UNIT for ch in raw):
        value = _cn_to_number(raw)
        return str(value) if value is not None else None
    return raw.replace(",", "")


class STTProvider(Protocol):
    """語音轉文字 provider 介面。"""

    def transcribe(
        self,
        audio_data: bytes,
        language: str = "zh",
        *,
        filename: str = "audio.webm",
        content_type: str = "audio/webm",
    ) -> "TranscriptionResult":
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
        filename: str = "audio.webm",
        content_type: str = "audio/webm",
    ) -> TranscriptionResult:
        """語音轉文字。

        Args:
            audio_data: 音訊原始資料
            authz: AuthorizationContext（必須，不繞過 PEP）
            language: 語言
            max_seconds: 最大音訊長度（秒）
            filename: 上傳檔名（影響 OpenAI 對格式的判斷）
            content_type: MIME type

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
            result = self._stt.transcribe(
                audio_data,
                language=language,
                filename=filename,
                content_type=content_type,
            )
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

        # 阿拉伯數字或中文數字（一百二／兩百／三千五）
        num = r'([0-9,]+(?:\.[0-9]+)?|[零一二三四五六七八九十百千兩]+)'
        fields = []
        patterns = {
            # 總金額類（語意上是總價；單價請用 unit_price）
            "amount": (
                r'(?:金額|總價|總金額|價格|費用|成本)\s*[：:是為]?\s*'
                + num + r'\s*(?:元|萬|千|塊)?'
            ),
            "unit_price": (
                r'(?:單價|每件|每個|每台|一個|一件|一台)\s*[：:是為]?\s*'
                + num + r'\s*(?:元|塊)?'
            ),
            "part_number": r'(?:料號|零件號|品號|型號)\s*[：:是]?\s*([A-Z0-9\-]+)',
            # 關鍵字前綴，或直接「兩百個／200 件」這類單位錨定說法
            "quantity": (
                r'(?:數量|件數)\s*[：:是為]?\s*' + num + r'\s*(?:個|件|台|批)?'
                r'|(?<![\w\u4e00-\u9fff])' + num + r'\s*(?:個|件|台|批)'
            ),
            "date": r'(?:日期|時間|期限|截止)\s*[：:是]?\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}月\d{1,2}日)',
            # 關鍵字前綴，或「幫台中精機報價／給某某公司開單」這類動詞框架
            "customer": (
                r'(?:客戶|客戶名稱|公司|對方)\s*[：:是]?\s*'
                r'([\u4e00-\u9fff]+(?:公司|股份有限公司|有限公司)?)'
                r'|(?:幫|給|向|跟|和)\s*([\u4e00-\u9fff]{2,8}?)'
                r'\s*(?:報價|估價|開報價單|開單|下單)'
            ),
        }

        for field_type in field_types:
            pattern = patterns.get(field_type)
            if not pattern:
                continue
            for match in re.findall(pattern, text):
                # 多組 alternation 時 findall 回傳 tuple，取第一個非空組
                value = match
                if isinstance(match, tuple):
                    value = next((g for g in match if g), "")
                if not value:
                    continue
                if field_type in {"amount", "unit_price", "quantity"}:
                    value = _normalize_number(value)
                    if value is None:
                        continue
                fields.append({
                    "type": field_type,
                    "value": value,
                    "raw_span": value,
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

def _sniff_audio_identity(audio_data: bytes, filename: str, content_type: str) -> tuple[str, str]:
    """依 magic bytes／上傳標頭推斷 OpenAI 可接受的檔名與 MIME。"""
    name = (filename or "").strip() or "audio.webm"
    ctype = (content_type or "").split(";")[0].strip().lower()
    head = audio_data[:16] if audio_data else b""

    if head.startswith(b"RIFF") and b"WAVE" in audio_data[:16]:
        return "audio.wav", "audio/wav"
    if head.startswith(b"OggS"):
        return "audio.ogg", "audio/ogg"
    if head.startswith(b"fLaC"):
        return "audio.flac", "audio/flac"
    if head.startswith(b"ID3") or head[:2] == b"\xff\xfb" or head[:2] == b"\xff\xf3":
        return "audio.mp3", "audio/mpeg"
    # webm / matroska
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "audio.webm", "audio/webm"
    # mp4 / m4a
    if len(head) >= 8 and head[4:8] in (b"ftyp", b"moov", b"mdat"):
        return "audio.m4a", "audio/mp4"

    if name.lower().endswith((".mp3", ".mpeg", ".mpga")) or "mpeg" in ctype or "mp3" in ctype:
        return "audio.mp3", "audio/mpeg"
    if name.lower().endswith((".wav",)) or "wav" in ctype:
        return "audio.wav", "audio/wav"
    if name.lower().endswith((".ogg", ".oga")) or "ogg" in ctype:
        return "audio.ogg", "audio/ogg"
    if name.lower().endswith((".m4a", ".mp4")) or "mp4" in ctype:
        return "audio.m4a", "audio/mp4"
    if name.lower().endswith((".webm",)) or "webm" in ctype:
        return "audio.webm", "audio/webm"
    return name if "." in name else "audio.webm", ctype or "audio/webm"


class OpenAISTTProvider:
    """OpenAI STT (gpt-transcribe / gpt-4o-mini-transcribe / whisper-1)."""

    # gpt-transcribe／gpt-4o-*-transcribe 不支援 verbose_json（僅 json/text）；
    # whisper-1 才支援 verbose_json（含 segments／duration）。
    _VERBOSE_JSON_MODELS = frozenset({"whisper-1"})

    def transcribe(
        self,
        audio_data: bytes,
        language: str = "zh",
        *,
        filename: str = "audio.webm",
        content_type: str = "audio/webm",
    ) -> TranscriptionResult:
        import io
        from app.config import settings

        try:
            from openai import OpenAI
        except ImportError:
            raise RuntimeError("openai package not installed")

        model = settings.VOICE_STT_MODEL
        # 新模型誤用 verbose_json 會 400 → 前端看到「provider error」
        response_format = (
            "verbose_json" if model in self._VERBOSE_JSON_MODELS else "json"
        )
        fname, mime = _sniff_audio_identity(audio_data, filename, content_type)

        client = OpenAI()
        result = client.audio.transcriptions.create(
            model=model,
            file=(fname, io.BytesIO(audio_data), mime),
            language=language,
            response_format=response_format,
        )

        segments = []
        if hasattr(result, "segments") and result.segments:
            segments = [
                {
                    "start": getattr(s, "start", None) if not isinstance(s, dict) else s.get("start", 0),
                    "end": getattr(s, "end", None) if not isinstance(s, dict) else s.get("end", 0),
                    "text": getattr(s, "text", None) if not isinstance(s, dict) else s.get("text", ""),
                }
                for s in result.segments
            ]

        duration = getattr(result, "duration", None) or 0.0
        # json 格式無 duration：粗估（webm/opus ~12KB/s）供上限檢查與成本計量
        if not duration and audio_data:
            duration = max(0.5, len(audio_data) / 12000.0)

        text = getattr(result, "text", None)
        if text is None and isinstance(result, dict):
            text = result.get("text", "")

        return TranscriptionResult(
            text=text or "",
            language=language,
            segments=segments,
            duration_seconds=float(duration),
            confidence=0.0,  # OpenAI 不直接回傳 confidence
        )


class OpenAITTSProvider:
    """OpenAI TTS (gpt-4o-mini-tts). 2026 latest."""

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

    def transcribe(
        self,
        audio_data: bytes,
        language: str = "zh",
        *,
        filename: str = "audio.webm",
        content_type: str = "audio/webm",
    ) -> TranscriptionResult:
        raise NotImplementedError("Azure STT not yet implemented — set VOICE_STT_PROVIDER=openai")


class AzureTTSProvider:
    """Azure Speech Service TTS（待實作）。"""

    def synthesize(self, text: str, voice: str = "alloy") -> bytes:
        raise NotImplementedError("Azure TTS not yet implemented — set VOICE_TTS_PROVIDER=openai")


# ── Local Provider stubs（待本機模型整合時實作）──

class LocalSTTProvider:
    """本機 STT（如 Whisper.cpp，待實作）。"""

    def transcribe(
        self,
        audio_data: bytes,
        language: str = "zh",
        *,
        filename: str = "audio.webm",
        content_type: str = "audio/webm",
    ) -> TranscriptionResult:
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