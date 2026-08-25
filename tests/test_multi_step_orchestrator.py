"""VISION Phase 2 — MultiStepOrchestrator / ToolRouter / refusal 單元測試。"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.services.catalog_retrieval import RetrievalHit
from app.services.multi_step_orchestrator import MultiStepOrchestrator
from app.services.query_plan import build_query_plan
from app.services.refusal import build_refusal
from app.services.tool_router import arms_for_plan, queries_for_arm


def _hit(name: str) -> RetrievalHit:
    return RetrievalHit(
        granularity="catalog",
        provider="enclave",
        authority_class="primary_document",
        document_id=str(uuid4()),
        filename=name,
        chunk_index=None,
        score=1.0,
        content_or_summary=name,
        citation_ok=True,
    )


class TestToolRouter:
    def test_inventory_arms(self):
        plan = build_query_plan("有哪些憑證文件")
        assert "catalog" in arms_for_plan(plan)

    def test_composite_queries(self):
        plan = build_query_plan("入出境相關文件與人資相關文件各有哪些")
        qs = queries_for_arm(plan, "catalog", plan.notes)
        assert len(qs) == 2


class TestRefusal:
    def test_unanswerable_message(self):
        r = build_refusal(question="火星殖民預算", plan_intent="unanswerable")
        assert r["reason"] == "unanswerable_intent"
        assert "未收錄" in r["message"] or "拒絕" in r["message"]

    def test_no_evidence_guesses_topic(self):
        r = build_refusal(question="營業稅繳款書稅額", plan_intent="fact")
        assert r["reason"] == "no_evidence"
        assert any("營業稅" in d for d in r["missing_docs"])


class TestMultiStep:
    def test_inventory_runs_catalog_and_chunk(self):
        facade = MagicMock()

        async def gw(**kw):
            return SimpleNamespace(
                results=[{
                    "id": "1",
                    "content": "x",
                    "score": 1,
                    "document_id": str(uuid4()),
                    "provider": "enclave",
                    "metadata": {"filename": "a.pdf"},
                }],
                citations=[],
                gateway_status="success",
                audit_trail=SimpleNamespace(
                    providers_called=["document"],
                    fusion_policy_version="1.0",
                    query_domain="internal_records",
                    dropped_non_citable=0,
                ),
            )

        facade.search_gateway = gw
        facade.search_catalog = MagicMock(return_value=[_hit("稅繳款書.pdf")])
        authz = MagicMock()
        authz.tenant_id = uuid4()

        with patch(
            "app.services.retrieval_facade.get_retrieval_facade", return_value=facade
        ), patch("app.services.kb_scope_policy.resolve_kb_revision_scope", return_value={}):
            out = asyncio.run(
                MultiStepOrchestrator().run(
                    authz=authz,
                    question="哪些掃描件屬於財務憑證？列出文件名",
                )
            )
        assert out["has_evidence"] is True
        assert out["catalog_hits"]
        assert out["trace"]["steps"]
        assert any(s["arm"] == "catalog" for s in out["trace"]["steps"])

    def test_unanswerable_forces_refusal(self):
        facade = MagicMock()

        async def gw(**kw):
            return SimpleNamespace(
                results=[{
                    "id": "1",
                    "content": "noise",
                    "score": 0.9,
                    "document_id": str(uuid4()),
                    "provider": "enclave",
                    "metadata": {"filename": "noise.pdf"},
                }],
                citations=[],
                gateway_status="success",
                audit_trail=SimpleNamespace(providers_called=["document"]),
            )

        facade.search_gateway = gw
        authz = MagicMock()
        authz.tenant_id = uuid4()
        with patch(
            "app.services.retrieval_facade.get_retrieval_facade", return_value=facade
        ), patch("app.services.kb_scope_policy.resolve_kb_revision_scope", return_value={}):
            out = asyncio.run(
                MultiStepOrchestrator().run(
                    authz=authz,
                    question="這批文件裡有沒有提到火星殖民計畫的預算？",
                )
            )
        assert out["query_plan"]["intent"] == "unanswerable"
        assert out["has_evidence"] is False
        assert out["refusal"]

    def test_filename_mention_scopes_chunk_retrieval(self):
        facade = MagicMock()
        scoped_calls = []

        def scoped_search(**kw):
            scoped_calls.append(kw)
            return SimpleNamespace(
                results=[{
                    "id": "s1",
                    "content": "顧問服務合約 八策數位",
                    "score": 0.99,
                    "document_id": str(uuid4()),
                    "metadata": {"filename": "009_DOC003~3.pdf", "chunk_index": 0},
                }],
                citations=[],
            )

        async def gw(**kw):
            raise AssertionError("全域搜尋應在 scoped 命中時跳過")

        facade.search = scoped_search
        facade.search_gateway = gw
        authz = MagicMock()
        authz.tenant_id = uuid4()
        with patch(
            "app.services.retrieval_facade.get_retrieval_facade", return_value=facade
        ), patch("app.services.kb_scope_policy.resolve_kb_revision_scope", return_value={}):
            out = asyncio.run(
                MultiStepOrchestrator().run(
                    authz=authz,
                    question="根據文件《009_DOC003~3.pdf》，文件標題是什麼？",
                )
            )
        assert scoped_calls, "應以 filename scope 做檔名導向檢索"
        assert scoped_calls[0]["scope"] == {"filename": "009_DOC003~3.pdf"}
        assert out["results"][0]["filename"] == "009_DOC003~3.pdf"
        assert out["results"][0]["source"] == "filename_scoped"
        assert any(
            s["arm"] == "chunk_scoped" for s in out["trace"]["steps"]
        )

    def test_filename_mention_falls_back_to_global_when_scoped_empty(self):
        facade = MagicMock()

        def empty_scoped(**kw):
            return SimpleNamespace(results=[], citations=[])

        async def gw(**kw):
            return SimpleNamespace(
                results=[{
                    "id": "g1",
                    "content": "global",
                    "score": 0.5,
                    "document_id": str(uuid4()),
                    "provider": "enclave",
                    "metadata": {"filename": "other.pdf"},
                }],
                citations=[],
                gateway_status="success",
                audit_trail=SimpleNamespace(providers_called=["document"]),
            )

        facade.search = empty_scoped
        facade.search_gateway = gw
        authz = MagicMock()
        authz.tenant_id = uuid4()
        with patch(
            "app.services.retrieval_facade.get_retrieval_facade", return_value=facade
        ), patch("app.services.kb_scope_policy.resolve_kb_revision_scope", return_value={}):
            out = asyncio.run(
                MultiStepOrchestrator().run(
                    authz=authz,
                    question="根據文件《不存在.pdf》，標題是什麼？",
                )
            )
        assert any(s["arm"] == "chunk" for s in out["trace"]["steps"])
