"""
P9-6 — LLM 統一客戶端

統一封裝 OpenAI API 與 Ollama 本機 LLM 的呼叫介面。
透過 settings.LLM_PROVIDER 決定使用哪個後端：
  - "openai"  → OpenAI API（gpt-4o-mini 等）
  - "ollama"  → 本機 Ollama（llama3.2 / qwen2.5 等）

使用方式：
    from app.services.llm_client import llm

    # 同步呼叫
    text = llm.complete(system_prompt, user_message)

    # 非同步串流（SSE）
    async for chunk in llm.stream(system_prompt, user_message):
        yield chunk
"""
from __future__ import annotations

import json
import logging
from typing import AsyncIterator, Iterator, Optional

import httpx

from app.config import settings
from app.services.deployment_mode import resolve_runtime_profiles_no_db

logger = logging.getLogger(__name__)

# ── 嘗試匯入 OpenAI ───────────────────────────────
try:
    import openai as openai_lib
    _HAS_OPENAI = True
except ImportError:
    _HAS_OPENAI = False
    logger.warning("openai 套件未安裝，openai 模式不可用")


class LLMClient:
    """
    LLM 統一介面，支援 OpenAI API 與 Ollama。

    設計原則：
    - 同一介面，切換只需改 .env 中的 LLM_PROVIDER
    - 錯誤訊息統一處理，對上層透明
    - 串流（stream）與非串流介面分開，避免混用
    """

    def __init__(self, provider: str = None, model: str = None, base_url: str = None):
        """
        可透過參數覆蓋全域設定，用於內部任務（分類、改寫）使用不同的 LLM。

        Args:
            provider: 覆蓋 LLM_PROVIDER（"openai" | "gemini" | "ollama"）
            model:    覆蓋預設模型名稱
            base_url: 覆蓋 Ollama base URL（容器內需用 host.docker.internal）
        """
        self.provider = (provider or settings.LLM_PROVIDER).lower()

        if self.provider == "openai":
            if not _HAS_OPENAI:
                raise RuntimeError("LLM_PROVIDER=openai 但 openai 套件未安裝")
            api_key = getattr(settings, "OPENAI_API_KEY", "")
            if not api_key:
                raise RuntimeError("LLM_PROVIDER=openai 但 OPENAI_API_KEY 未設定")
            self._openai_sync  = openai_lib.OpenAI(api_key=api_key)
            self._openai_async = openai_lib.AsyncOpenAI(api_key=api_key)
            self._model = model or getattr(settings, "OPENAI_MODEL", "gpt-4o-mini")
            logger.info("LLMClient 初始化：OpenAI（model=%s）", self._model)

        elif self.provider == "gemini":
            if not _HAS_OPENAI:
                raise RuntimeError("LLM_PROVIDER=gemini 但 openai 套件未安裝")
            api_key = getattr(settings, "GEMINI_API_KEY", "")
            if not api_key:
                raise RuntimeError("LLM_PROVIDER=gemini 但 GEMINI_API_KEY 未設定")
            _GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
            self._openai_sync  = openai_lib.OpenAI(api_key=api_key, base_url=_GEMINI_BASE_URL)
            self._openai_async = openai_lib.AsyncOpenAI(api_key=api_key, base_url=_GEMINI_BASE_URL)
            self._model = model or getattr(settings, "GEMINI_MODEL", "gemini-3-flash-preview")
            logger.info("LLMClient 初始化：Gemini（model=%s）", self._model)

        elif self.provider == "ollama":
            self._ollama_url = base_url or getattr(settings, "OLLAMA_BASE_URL", "http://localhost:11434")
            self._model = model or getattr(settings, "OLLAMA_MODEL", "llama3.2")
            logger.info("LLMClient 初始化：Ollama（model=%s, url=%s）", self._model, self._ollama_url)

        else:
            raise ValueError(f"不支援的 LLM_PROVIDER：{self.provider}，請使用 openai、gemini 或 ollama")

    # ═══════════════════════════════════
    #  同步介面
    # ═══════════════════════════════════

    def complete(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
    ) -> str:
        """非串流呼叫，回傳完整回答字串。"""
        max_tokens = max_tokens or getattr(settings, "GENERATION_MAX_TOKENS", 3000)

        if self.provider in ("openai", "gemini"):
            return self._openai_complete(system_prompt, user_message, temperature, max_tokens)
        else:
            return self._ollama_complete(system_prompt, user_message, temperature, max_tokens)

    def _openai_complete(self, system_prompt, user_message, temperature, max_tokens) -> str:
        resp = self._openai_sync.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_message},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content or ""

    def _ollama_complete(self, system_prompt, user_message, temperature, max_tokens) -> str:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_message},
            ],
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        with httpx.Client(timeout=120) as client:
            resp = client.post(f"{self._ollama_url}/api/chat", json=payload)
            resp.raise_for_status()
            return resp.json()["message"]["content"]

    # ═══════════════════════════════════
    #  非同步串流介面
    # ═══════════════════════════════════

    async def stream(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[str]:
        """非同步串流，每次 yield 一個字串片段（chunk）。"""
        max_tokens = max_tokens or getattr(settings, "GENERATION_MAX_TOKENS", 3000)

        if self.provider in ("openai", "gemini"):
            async for chunk in self._openai_stream(system_prompt, user_message, temperature, max_tokens):
                yield chunk
        else:
            async for chunk in self._ollama_stream(system_prompt, user_message, temperature, max_tokens):
                yield chunk

    async def _openai_stream(self, system_prompt, user_message, temperature, max_tokens) -> AsyncIterator[str]:
        stream = await self._openai_async.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_message},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    async def _ollama_stream(self, system_prompt, user_message, temperature, max_tokens) -> AsyncIterator[str]:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_message},
            ],
            "stream": True,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream("POST", f"{self._ollama_url}/api/chat", json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.strip():
                        try:
                            data = json.loads(line)
                            content = data.get("message", {}).get("content", "")
                            if content:
                                yield content
                        except json.JSONDecodeError:
                            continue

    # ═══════════════════════════════════
    #  工具方法
    # ═══════════════════════════════════

    def health_check(self) -> dict:
        """健康檢查，回傳 provider 狀態。"""
        try:
            result = self.complete("你是助理", "回答「OK」即可", temperature=0, max_tokens=5)
            return {"provider": self.provider, "model": self._model, "status": "ok", "response": result}
        except Exception as e:
            return {"provider": self.provider, "model": self._model, "status": "error", "error": str(e)}


# ── 全域單例 ──────────────────────────────────────
# 延遲初始化，避免在 import 時就要求環境變數
_llm_instance: Optional[LLMClient] = None


def get_llm() -> LLMClient:
    """依目前 deployment mode 取得 LLMClient（每次請求重新解析 preset）。"""
    profiles = resolve_runtime_profiles_no_db()
    main = profiles.get("main", {})
    provider = str(main.get("provider", getattr(settings, "LLM_PROVIDER", "openai"))).lower()
    model = str(main.get("model", "")) or None
    base_url = None
    if provider == "ollama":
        base_url = str(main.get("base_url", getattr(settings, "OLLAMA_BASE_URL", "http://localhost:11434")))
    return LLMClient(provider=provider, model=model, base_url=base_url)


# 方便直接 from app.services.llm_client import llm 使用
class _LazyLLM:
    """Lazy proxy，首次呼叫時才初始化 LLMClient。"""
    def _get(self) -> LLMClient:
        return get_llm()

    def complete(self, *args, **kwargs) -> str:
        return self._get().complete(*args, **kwargs)

    async def stream(self, *args, **kwargs) -> AsyncIterator[str]:
        async for chunk in self._get().stream(*args, **kwargs):
            yield chunk

    def health_check(self) -> dict:
        return self._get().health_check()

    @property
    def provider(self) -> str:
        return self._get().provider

    @property
    def model(self) -> str:
        return self._get()._model


llm = _LazyLLM()
