"""Regression tests for the 2026-08-03 WeKnora wiki integration fixes.

Covers the three bugs found during live seeding:
1. weknora_http.list_wiki_pages — WeKnora returns {"pages": [...]}, not {"data": [...]}
2. wiki_compiler._compile_via_weknora — must list pages, filter placeholders,
   prefer index page, and surface the remote title
3. endpoints/wiki.get_wiki_page — citation_map entries enriched with document filename
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import httpx
import pytest
import respx

from app.gateway.adapters.weknora_http import WeKnoraHTTPAdapter
from app.services.wiki_compiler import WikiCompiler

BASE = "http://weknora.test"
KB_ID = uuid.uuid4()


class TestListWikiPagesParsing:
    @respx.mock
    async def test_data_key_shape(self):
        respx.get(f"{BASE}/api/v1/knowledgebase/{KB_ID}/wiki/pages").mock(
            return_value=httpx.Response(200, json={"data": [{"slug": "a"}]})
        )
        adapter = WeKnoraHTTPAdapter(base_url=BASE, api_key="k")
        pages = await adapter.list_wiki_pages(KB_ID)
        assert pages == [{"slug": "a"}]

    @respx.mock
    async def test_pages_key_shape(self):
        """Actual WeKnora shape — the bug that made seeding see zero pages."""
        respx.get(f"{BASE}/api/v1/knowledgebase/{KB_ID}/wiki/pages").mock(
            return_value=httpx.Response(200, json={"pages": [{"slug": "index-x"}]})
        )
        adapter = WeKnoraHTTPAdapter(base_url=BASE, api_key="k")
        pages = await adapter.list_wiki_pages(KB_ID)
        assert pages == [{"slug": "index-x"}]

    @respx.mock
    async def test_empty_payload_returns_empty_list(self):
        respx.get(f"{BASE}/api/v1/knowledgebase/{KB_ID}/wiki/pages").mock(
            return_value=httpx.Response(200, json={})
        )
        adapter = WeKnoraHTTPAdapter(base_url=BASE, api_key="k")
        assert await adapter.list_wiki_pages(KB_ID) == []

    @respx.mock
    async def test_http_error_returns_empty_list(self):
        respx.get(f"{BASE}/api/v1/knowledgebase/{KB_ID}/wiki/pages").mock(
            return_value=httpx.Response(500, json={"error": "boom"})
        )
        adapter = WeKnoraHTTPAdapter(base_url=BASE, api_key="k")
        assert await adapter.list_wiki_pages(KB_ID) == []


class FakeAdapter:
    """Stands in for WeKnoraHTTPAdapter inside _compile_via_weknora."""

    pages: list = []
    raise_on_list: bool = False

    def __init__(self, **kwargs):
        pass

    async def compile_wiki(self, kb_id):
        return {"status": "ok"}

    async def list_wiki_pages(self, kb_id):
        if type(self).raise_on_list:
            raise RuntimeError("weknora unreachable")
        return type(self).pages


@pytest.fixture
def fake_weknora(monkeypatch):
    monkeypatch.setenv("WEKNORA_ENABLED", "true")
    FakeAdapter.pages = []
    FakeAdapter.raise_on_list = False
    monkeypatch.setattr(
        "app.gateway.adapters.weknora_http.WeKnoraHTTPAdapter", FakeAdapter
    )
    monkeypatch.setattr(
        "app.gateway.token_provider.build_weknora_token_provider", lambda: None
    )
    return FakeAdapter


class TestCompileViaWeknora:
    async def test_filters_placeholder_and_empty_pages(self, fake_weknora):
        fake_weknora.pages = [
            {"slug": "s1", "title": "placeholder",
             "data": {"content": "Auto-compiled placeholder"}},
            {"slug": "s2", "title": "empty", "data": {"content": ""}},
            {"slug": "s3", "title": "真實頁面",
             "data": {"content": "# 真內容", "citations": [{"document_id": "d1"}]}},
        ]
        result = await WikiCompiler()._compile_via_weknora(KB_ID, "summary")
        assert result is not None
        assert result["content"] == "# 真內容"
        assert result["title"] == "真實頁面"
        assert result["citation_map"] == [{"document_id": "d1"}]
        assert result["provider"] == "weknora"

    async def test_prefers_index_page(self, fake_weknora):
        fake_weknora.pages = [
            {"slug": "summary-zzz", "title": "一般頁",
             "data": {"content": "一般內容"}},
            {"slug": "index-abc", "title": "索引頁",
             "data": {"content": "索引內容"}},
        ]
        result = await WikiCompiler()._compile_via_weknora(KB_ID, "summary")
        assert result["content"] == "索引內容"
        assert result["title"] == "索引頁"

    async def test_page_type_mismatch_skipped(self, fake_weknora):
        fake_weknora.pages = [
            {"slug": "s1", "title": "entity 頁", "page_type": "entity",
             "data": {"content": "entity 內容"}},
            {"slug": "s2", "title": "summary 頁", "page_type": "summary",
             "data": {"content": "summary 內容"}},
        ]
        result = await WikiCompiler()._compile_via_weknora(KB_ID, "summary")
        assert result["content"] == "summary 內容"

    async def test_no_candidates_returns_none(self, fake_weknora):
        fake_weknora.pages = [
            {"slug": "s1", "data": {"content": "Auto-compiled placeholder"}},
        ]
        assert await WikiCompiler()._compile_via_weknora(KB_ID, "summary") is None

    async def test_adapter_failure_returns_none_not_raise(self, fake_weknora):
        fake_weknora.raise_on_list = True
        assert await WikiCompiler()._compile_via_weknora(KB_ID, "summary") is None

    async def test_disabled_returns_none(self, monkeypatch):
        monkeypatch.setenv("WEKNORA_ENABLED", "false")
        assert await WikiCompiler()._compile_via_weknora(KB_ID, "summary") is None


class TestGetWikiPageCitationEnrichment:
    def _seed(self, db):
        import app.models  # noqa: F401
        from app.models.tenant import Tenant
        from app.models.knowledge_base import KnowledgeBase
        from app.models.document import Document
        from app.models.wiki import WikiPage, WikiRevision

        tenant = Tenant(id=uuid.uuid4(), name="WikiEnrich", plan="free", status="active")
        db.add(tenant)
        db.flush()
        kb = KnowledgeBase(id=uuid.uuid4(), tenant_id=tenant.id, name="kb-wiki", status="active")
        doc = Document(
            id=uuid.uuid4(), tenant_id=tenant.id,
            filename="員工手冊.pdf", file_type="pdf", status="completed",
        )
        db.add_all([kb, doc])
        db.flush()
        page = WikiPage(
            id=uuid.uuid4(), tenant_id=tenant.id, kb_id=kb.id,
            slug="summary-x", title="公司制度總覽", page_type="summary",
            status="published", source_document_ids=[str(doc.id)],
            active_revision=1,
        )
        db.add(page)
        db.flush()
        rev = WikiRevision(
            wiki_page_id=page.id, revision=1, content="# 內容",
            content_hash="abc123",
            citation_map=[
                {"document_id": str(doc.id), "revision": 1},
                {"title": "外部來源"},
            ],
            compile_job_id="job-1",
        )
        db.add(rev)
        db.commit()
        return tenant, doc, page

    def test_citation_map_enriched_with_filename(self, test_engine):
        import app.models  # noqa: F401
        from app.db.base_class import Base
        from sqlalchemy.orm import sessionmaker
        from fastapi import Response
        from app.api.v1.endpoints.wiki import get_wiki_page

        Base.metadata.create_all(bind=test_engine)
        Session = sessionmaker(bind=test_engine)
        db = Session()
        try:
            tenant, doc, page = self._seed(db)
            fake_user = SimpleNamespace(
                id=uuid.uuid4(), tenant_id=tenant.id, role="owner",
                department_id=None, department=None, is_superuser=True,
            )
            result = get_wiki_page(
                page_id=page.id, response=Response(), db=db, current_user=fake_user,
            )
            citations = result["citation_map"]
            assert citations[0]["filename"] == "員工手冊.pdf"
            assert citations[0]["document_id"] == str(doc.id)
            # 無 document_id 的引用不應被塞入 filename
            assert "filename" not in citations[1]
            assert result["title"] == "公司制度總覽"
        finally:
            db.close()

    def test_cross_tenant_page_returns_404(self, test_engine):
        import app.models  # noqa: F401
        from app.db.base_class import Base
        from sqlalchemy.orm import sessionmaker
        from fastapi import HTTPException, Response
        from app.api.v1.endpoints.wiki import get_wiki_page

        Base.metadata.create_all(bind=test_engine)
        Session = sessionmaker(bind=test_engine)
        db = Session()
        try:
            tenant, doc, page = self._seed(db)
            outsider = SimpleNamespace(
                id=uuid.uuid4(), tenant_id=uuid.uuid4(), role="owner",
                department_id=None, department=None, is_superuser=True,
            )
            with pytest.raises(HTTPException) as ei:
                get_wiki_page(
                    page_id=page.id, response=Response(), db=db, current_user=outsider,
                )
            assert ei.value.status_code == 404
        finally:
            db.close()
