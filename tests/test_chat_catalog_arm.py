"""ADR-008 契約 4：chat 盤點臂契約測試。

- 盤點型查詢 → catalog 命中進 context_parts / sources / retrieval.arms
- 非盤點查詢 → 不呼叫 catalog
- catalog 失敗不阻斷 chunk 主路徑
- chunk 無命中但 catalog 有命中 → 仍視為有證據（不落入「查無資料」）
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.services.catalog_retrieval import RetrievalHit
from app.services.chat_orchestrator import ChatOrchestrator


def _hit(filename: str) -> RetrievalHit:
    return RetrievalHit(
        granularity="catalog",
        provider="enclave",
        authority_class="primary_document",
        document_id=str(uuid4()),
        filename=filename,
        chunk_index=None,
        score=1.0,
        content_or_summary=f"文件：{filename}",
        citation_ok=True,
    )


def _make_orch() -> ChatOrchestrator:
    orch = ChatOrchestrator.__new__(ChatOrchestrator)
    return orch


def _gateway_retrieved():
    return SimpleNamespace(
        results=[],
        citations=[],
        gateway_status="success",
        audit_trail=SimpleNamespace(providers_called=["enclave"]),
    )


def _run_retrieve(question: str, *, catalog_hits, catalog_raises=None, chunk_results=None):
    orch = _make_orch()
    facade = MagicMock()
    facade.search_gateway = MagicMock(return_value=_gateway_retrieved())
    retrieved = _gateway_retrieved()
    retrieved.results = chunk_results or []

    async def fake_search_gateway(**kw):
        return retrieved

    facade.search_gateway = fake_search_gateway
    if catalog_raises is not None:
        facade.search_catalog = MagicMock(side_effect=catalog_raises)
    else:
        facade.search_catalog = MagicMock(return_value=catalog_hits)

    authz = MagicMock()
    authz.tenant_id = uuid4()

    with patch(
        "app.services.retrieval_facade.get_retrieval_facade", return_value=facade
    ), patch(
        "app.services.kb_scope_policy.resolve_kb_revision_scope",
        return_value={},
    ):
        ctx = asyncio.run(
            orch.retrieve_context(tenant_id=uuid4(), question=question, authz=authz)
        )
    return ctx, facade


class TestChatCatalogArm:
    def test_inventory_query_includes_catalog_in_context(self):
        ctx, facade = _run_retrieve(
            "庫裡有哪些文件？",
            catalog_hits=[_hit("a.pdf"), _hit("b.pdf")],
        )
        facade.search_catalog.assert_called_once()
        assert "catalog" in ctx["retrieval"]["arms"]
        listing = ctx["context_parts"][0]
        assert "庫內文件清單" in listing
        assert "a.pdf" in listing and "b.pdf" in listing
        catalog_sources = [s for s in ctx["sources"] if s.get("granularity") == "catalog"]
        assert len(catalog_sources) == 2
        assert all(s["title"] for s in catalog_sources)

    def test_non_inventory_query_skips_catalog(self):
        ctx, facade = _run_retrieve(
            "加班費怎麼算？",
            catalog_hits=[],
        )
        facade.search_catalog.assert_not_called()
        assert ctx["retrieval"]["arms"] == ["chunk"]

    def test_catalog_failure_does_not_break_chunk_path(self):
        ctx, facade = _run_retrieve(
            "庫裡有哪些文件？",
            catalog_hits=None,
            catalog_raises=RuntimeError("db down"),
        )
        facade.search_catalog.assert_called_once()
        # F4：arms 反映 QueryPlan 意圖（仍含 catalog），即使執行失敗也不阻斷 chunk
        assert "catalog" in ctx["retrieval"]["arms"]
        assert "chunk" in ctx["retrieval"]["arms"]
        assert ctx["retrieval"]["query_plan"]["intent"] == "inventory"
        assert ctx["question"] == "庫裡有哪些文件？"
        assert ctx["retrieval"]["label"]

    def test_catalog_only_hit_counts_as_evidence(self):
        # chunk 臂無命中，但 catalog 有命中 → 不應落入「查無資料」fallback
        ctx, _ = _run_retrieve(
            "庫裡有哪些文件？",
            catalog_hits=[_hit("a.pdf")],
            chunk_results=[],
        )
        assert "庫內文件清單" in ctx["context_parts"][0]
        assert "catalog" in ctx["retrieval"]["arms"]
