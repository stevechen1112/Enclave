"""Query embedding cache 測試（§7.2 P0 補強）。"""
import time

import pytest

import app.tasks.document_tasks as document_tasks
from app.config import settings
from app.services import embedding_cache
from app.services.embedding_cache import (
    _cache_key,
    embed_query_cached,
    get_cached_embedding,
    reset_cache_state,
    set_cached_embedding,
)


@pytest.fixture(autouse=True)
def _clean_cache():
    reset_cache_state()
    yield
    reset_cache_state()


def test_cache_key_is_deterministic_and_scoped():
    k1 = _cache_key("ollama", "bge-m3", "query", "如何維修機台")
    k2 = _cache_key("ollama", "bge-m3", "query", "如何維修機台")
    k3 = _cache_key("ollama", "bge-m3", "document", "如何維修機台")
    k4 = _cache_key("voyage", "bge-m3", "query", "如何維修機台")
    assert k1 == k2
    assert k1 != k3  # input_type 不同
    assert k1 != k4  # provider 不同


def test_memory_fallback_roundtrip(monkeypatch):
    monkeypatch.setattr(embedding_cache, "_redis", lambda: None)
    set_cached_embedding(
        provider="ollama", model="bge-m3", text="q", embedding=[0.1, 0.2]
    )
    assert get_cached_embedding(provider="ollama", model="bge-m3", text="q") == [
        0.1,
        0.2,
    ]
    assert (
        get_cached_embedding(provider="ollama", model="bge-m3", text="other") is None
    )


def test_embed_query_cached_avoids_duplicate_provider_calls(monkeypatch):
    monkeypatch.setattr(embedding_cache, "_redis", lambda: None)
    calls = []

    def fake_embed(texts, input_type="document"):
        calls.append((tuple(texts), input_type))
        return [[1.0, 2.0, 3.0]]

    monkeypatch.setattr(document_tasks, "embed_texts", fake_embed)
    monkeypatch.setattr(
        embedding_cache,
        "resolve_embedding_profile",
        lambda: ("ollama", "bge-m3"),
    )
    first = embed_query_cached("同一句查詢")
    second = embed_query_cached("同一句查詢")
    assert first == second == [1.0, 2.0, 3.0]
    assert len(calls) == 1  # 第二次命中快取，零 provider 呼叫
    assert calls[0][1] == "query"


def test_cache_disabled_always_misses(monkeypatch):
    monkeypatch.setattr(embedding_cache, "_redis", lambda: None)
    monkeypatch.setattr(settings, "EMBEDDING_CACHE_ENABLED", False)
    set_cached_embedding(
        provider="ollama", model="bge-m3", text="q", embedding=[9.9]
    )
    assert get_cached_embedding(provider="ollama", model="bge-m3", text="q") is None


def test_memory_entry_expires(monkeypatch):
    monkeypatch.setattr(embedding_cache, "_redis", lambda: None)
    monkeypatch.setattr(settings, "EMBEDDING_CACHE_TTL_SECONDS", 1)
    set_cached_embedding(
        provider="ollama", model="bge-m3", text="q", embedding=[1.0]
    )
    assert get_cached_embedding(provider="ollama", model="bge-m3", text="q") == [1.0]
    real_time = time.time
    monkeypatch.setattr(time, "time", lambda: real_time() + 2)
    assert get_cached_embedding(provider="ollama", model="bge-m3", text="q") is None


def test_resolve_embedding_profile_matches_embed_texts(monkeypatch):
    monkeypatch.setattr(
        embedding_cache,
        "resolve_runtime_profiles_no_db",
        lambda: {"embedding": {"provider": "voyage", "model": "voyage-3-lite"}},
    )
    provider, model = embedding_cache.resolve_embedding_profile()
    assert provider == "voyage"
    assert model == "voyage-3-lite"


def test_retrieval_uses_cached_query_embedding():
    import inspect

    import app.services.kb_retrieval as kb_retrieval

    source = inspect.getsource(kb_retrieval.KnowledgeBaseRetriever._semantic_search)
    assert "embed_query_cached" in source
