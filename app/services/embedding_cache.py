"""Query embedding cache（ENGINEERING_PLAN §7.2 P0 補強第 4 項）。

高頻查詢的 embedding 是純函數（同 provider/model/input_type/text → 同向量），
但每次呼叫都產生 provider 費用與延遲。此層以 Redis 為主（多 worker 共享）、
程序內有界 dict 為 fallback（Redis 不可用時降級，不阻斷檢索）。

只快取 ``input_type="query"``；文件入庫的 document embedding 量大且一次性，
不快取以免撐爆 Redis。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import Dict, List, Optional, Tuple

from app.config import settings
from app.services.deployment_mode import resolve_runtime_profiles_no_db

logger = logging.getLogger(__name__)


def resolve_embedding_profile() -> tuple[str, str]:
    """與 ``embed_texts`` 同一來源解析 provider/model，避免快取鍵與實際向量不一致。"""
    embed_cfg = resolve_runtime_profiles_no_db().get("embedding", {})
    provider = str(
        embed_cfg.get("provider", getattr(settings, "EMBEDDING_PROVIDER", "voyage"))
    ).lower()
    default_model = (
        settings.VOYAGE_MODEL
        if provider == "voyage"
        else settings.OLLAMA_EMBED_MODEL
    )
    model = str(embed_cfg.get("model", default_model))
    return provider, model

_KEY_PREFIX = "emb_cache:"
_mem_cache: Dict[str, Tuple[float, List[float]]] = {}
_redis_client = None
_redis_failed = False


def _cache_key(provider: str, model: str, input_type: str, text: str) -> str:
    digest = hashlib.sha256(
        f"{provider}|{model}|{input_type}|{text}".encode("utf-8")
    ).hexdigest()
    return f"{_KEY_PREFIX}{digest}"


def _redis():
    global _redis_client, _redis_failed
    if _redis_failed:
        return None
    if _redis_client is None:
        try:
            import redis

            host = getattr(settings, "REDIS_HOST", None)
            if host:
                # production Redis 有密碼（compose 注入 REDIS_PASSWORD）
                pwd = os.environ.get("REDIS_PASSWORD", "")
                auth = f":{pwd}@" if pwd else ""
                url = f"redis://{auth}{host}:{int(getattr(settings, 'REDIS_PORT', 6379))}/3"
            else:
                url = getattr(settings, "CELERY_BROKER_URL", "redis://localhost:6379/3")
            _redis_client = redis.Redis.from_url(
                url, socket_connect_timeout=1, socket_timeout=1
            )
            _redis_client.ping()
        except Exception as exc:
            logger.warning("embedding cache Redis unavailable, fallback to memory: %s", exc)
            _redis_failed = True
            return None
    return _redis_client


def _mem_get(key: str) -> Optional[List[float]]:
    entry = _mem_cache.get(key)
    if entry is None:
        return None
    expires_at, value = entry
    if expires_at < time.time():
        _mem_cache.pop(key, None)
        return None
    return value


def _mem_set(key: str, value: List[float], ttl: int) -> None:
    max_entries = int(getattr(settings, "EMBEDDING_CACHE_MAX_ENTRIES", 10000))
    if len(_mem_cache) >= max_entries:
        # 簡易驅逐：清掉已過期項目；仍滿則清空最舊 10%
        now = time.time()
        expired = [k for k, (exp, _) in _mem_cache.items() if exp < now]
        for k in expired:
            _mem_cache.pop(k, None)
        if len(_mem_cache) >= max_entries:
            for k in sorted(_mem_cache, key=lambda k: _mem_cache[k][0])[: max_entries // 10]:
                _mem_cache.pop(k, None)
    _mem_cache[key] = (time.time() + ttl, value)


def get_cached_embedding(
    *, provider: str, model: str, text: str, input_type: str = "query"
) -> Optional[List[float]]:
    """查快取；未命中或停用回傳 None。"""
    if not getattr(settings, "EMBEDDING_CACHE_ENABLED", True):
        return None
    key = _cache_key(provider, model, input_type, text)
    client = _redis()
    if client is not None:
        try:
            raw = client.get(key)
            if raw:
                return json.loads(raw)
        except Exception as exc:
            logger.warning("embedding cache get failed: %s", exc)
    return _mem_get(key)


def set_cached_embedding(
    *,
    provider: str,
    model: str,
    text: str,
    embedding: List[float],
    input_type: str = "query",
) -> None:
    """寫快取；失敗靜默（快取不是關鍵路徑）。"""
    if not getattr(settings, "EMBEDDING_CACHE_ENABLED", True):
        return
    ttl = int(getattr(settings, "EMBEDDING_CACHE_TTL_SECONDS", 86400))
    key = _cache_key(provider, model, input_type, text)
    client = _redis()
    if client is not None:
        try:
            client.setex(key, ttl, json.dumps(embedding))
            return
        except Exception as exc:
            logger.warning("embedding cache set failed: %s", exc)
    _mem_set(key, embedding, ttl)


def embed_query_cached(text: str) -> List[float]:
    """取得 query embedding；命中快取則零 provider 呼叫。

    provider/model 一律由 ``resolve_embedding_profile()`` 解析，與 ``embed_texts`` 對齊。
    """
    provider, model = resolve_embedding_profile()
    cached = get_cached_embedding(
        provider=provider, model=model, text=text, input_type="query"
    )
    if cached is not None:
        return cached
    from app.tasks.document_tasks import embed_texts

    embedding = embed_texts([text], input_type="query")[0]
    set_cached_embedding(
        provider=provider, model=model, text=text, embedding=embedding, input_type="query"
    )
    return embedding


def reset_cache_state() -> None:
    """測試用：清空記憶體快取與 Redis 連線狀態。"""
    global _redis_client, _redis_failed
    _mem_cache.clear()
    _redis_client = None
    _redis_failed = False
