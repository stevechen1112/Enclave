"""Cloud vision OCR — optional enhancement arm for scanned documents.

Disabled unless CLOUD_OCR_PROVIDER is set (openai|gemini|mistral) together with
the matching API key. Grounded in the CV-RF-01b five-arm ablation
(artifacts/cloud_vision_*_ablation_last_run.json): dedicated OCR models beat
general-purpose ones; gemini-3-flash-preview and mistral-ocr-latest tied best
at 30.3% strict field hit vs DeepDOC 24.2%, and neither hallucinates on
handwriting the way gpt-5.6-luna did.
"""
from __future__ import annotations

import base64
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

PROMPT = (
    "這是一份掃描文件的其中一頁影像。請逐字轉錄頁面上的所有文字，"
    "保留原始繁體中文（不要轉成簡體）、數字、日期與表格內容。"
    "只輸出轉錄文字，不要加任何說明或格式標記。"
)

DEFAULT_MODELS = {
    "openai": "gpt-5.6-terra",
    "gemini": "gemini-3-flash-preview",
    "mistral": "mistral-ocr-latest",
}

_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "mistral": "MISTRAL_API_KEY",
}

IMAGE_EXTS = {"png", "jpg", "jpeg", "webp", "tiff"}
SUPPORTED_EXTS = IMAGE_EXTS | {"pdf"}


@dataclass
class CloudOCRResult:
    text: str
    provider: str
    model: str
    pages: int
    elapsed_ms: int
    retries: int = 0
    errors: List[Dict[str, str]] = field(default_factory=list)


def provider() -> Optional[str]:
    p = os.getenv("CLOUD_OCR_PROVIDER", "").lower().strip()
    return p if p in DEFAULT_MODELS else None


def is_enabled() -> bool:
    p = provider()
    return bool(p and os.getenv(_KEY_ENV[p]))


def model_for(p: str) -> str:
    return os.getenv("CLOUD_OCR_MODEL", "").strip() or DEFAULT_MODELS[p]


def _client(p: str) -> httpx.Client:
    key = os.environ[_KEY_ENV[p]]
    if p == "openai":
        return httpx.Client(base_url="https://api.openai.com/v1",
                            headers={"Authorization": f"Bearer {key}"}, timeout=180.0)
    if p == "gemini":
        return httpx.Client(base_url="https://generativelanguage.googleapis.com",
                            headers={"x-goog-api-key": key}, timeout=180.0)
    return httpx.Client(base_url="https://api.mistral.ai",
                        headers={"Authorization": f"Bearer {key}"}, timeout=180.0)


def _transcribe_page(client: httpx.Client, p: str, model: str, png: bytes) -> str:
    b64 = base64.b64encode(png).decode()
    if p == "openai":
        r = client.post("/chat/completions", json={
            "model": model,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ]}],
            "max_completion_tokens": 4096,
        })
    elif p == "gemini":
        r = client.post(f"/v1beta/models/{model}:generateContent", json={
            "contents": [{"parts": [
                {"text": PROMPT},
                {"inline_data": {"mime_type": "image/png", "data": b64}},
            ]}],
            "generationConfig": {"maxOutputTokens": 8192},
        })
    else:
        r = client.post("/v1/ocr", json={
            "model": model,
            "document": {"type": "image_url", "image_url": f"data:image/png;base64,{b64}"},
        })
    if r.status_code != 200:
        raise RuntimeError(f"http_{r.status_code}: {r.text[:200]}")
    data = r.json()
    if p == "openai":
        return (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    if p == "gemini":
        cands = data.get("candidates") or []
        if not cands:
            raise RuntimeError("no_candidates")
        return "".join(part.get("text", "")
                       for part in (cands[0].get("content") or {}).get("parts") or [])
    page = (data.get("pages") or [{}])[0]
    return page.get("markdown") or ""


def _rasterize(file_path: str, ext: str, dpi: int) -> List[bytes]:
    if ext in IMAGE_EXTS:
        with open(file_path, "rb") as f:
            return [f.read()]
    import fitz  # PyMuPDF — lazy import; only needed for PDF rasterization
    pages: List[bytes] = []
    pdf = fitz.open(file_path)
    try:
        for page in pdf:
            pages.append(page.get_pixmap(dpi=dpi).tobytes("png"))
    finally:
        pdf.close()
    return pages


def transcribe(file_path: str, ext: str, *, dpi: int = 200, max_retries: int = 3) -> CloudOCRResult:
    """Transcribe a scanned PDF/image via the configured cloud OCR provider."""
    p = provider()
    if not p:
        raise RuntimeError("cloud OCR not configured (set CLOUD_OCR_PROVIDER)")
    model = model_for(p)
    start = time.time()
    images = _rasterize(file_path, ext.lower(), dpi)
    client = _client(p)
    texts: List[str] = []
    retries = 0
    errors: List[Dict[str, str]] = []
    try:
        for i, png in enumerate(images):
            out = ""
            for attempt in range(max_retries):
                try:
                    out = _transcribe_page(client, p, model, png)
                    if out.strip():
                        break
                    retries += 1
                except Exception as exc:
                    retries += 1
                    if attempt == max_retries - 1:
                        errors.append({"page": str(i), "error": str(exc)[:200]})
                        logger.warning("cloud OCR page %s failed: %s", i, exc)
                time.sleep(2)
            texts.append(out)
    finally:
        client.close()
    return CloudOCRResult(
        text="\n".join(texts),
        provider=p,
        model=model,
        pages=len(images),
        elapsed_ms=int((time.time() - start) * 1000),
        retries=retries,
        errors=errors,
    )
