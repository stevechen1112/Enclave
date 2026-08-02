"""
Phase 2 — RAGFlow Adapter Contract Tests

Legacy RAGFlowAdapter is fail-closed stub; production uses RAGFlowHTTPAdapter.
"""
import uuid
import pytest
from app.core.authorization import AuthorizationContext
from app.gateway.adapters.ragflow import RAGFlowAdapter


def _make_authz():
    return AuthorizationContext(
        tenant_id=uuid.uuid4(),
        subject_id=uuid.uuid4(),
        role_ids=["admin"],
        policy_revision=1,
    )


class TestRAGFlowAdapter:
    @pytest.mark.asyncio
    async def test_capabilities(self):
        adapter = RAGFlowAdapter()
        caps = await adapter.capabilities()
        assert caps["provider"] == "ragflow"
        assert "parse" in caps["features"]

    @pytest.mark.asyncio
    async def test_health(self):
        adapter = RAGFlowAdapter()
        health = await adapter.health()
        assert health["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_ingest_fail_closed(self):
        adapter = RAGFlowAdapter()
        with pytest.raises(RuntimeError, match="stub"):
            await adapter.ingest(
                uuid.uuid4(), 1, "file://test.pdf", "abc123", "pdf", _make_authz(),
            )

    @pytest.mark.asyncio
    async def test_delete_fail_closed(self):
        adapter = RAGFlowAdapter()
        with pytest.raises(RuntimeError, match="stub"):
            await adapter.delete("document", "doc-1", 1, "idem-1")

    @pytest.mark.asyncio
    async def test_reconcile_never_fake_converged(self):
        adapter = RAGFlowAdapter()
        result = await adapter.reconcile("document", "doc-1", 1)
        assert result["converged"] is False

    @pytest.mark.asyncio
    async def test_parse_document_local_helpers(self):
        adapter = RAGFlowAdapter()
        result = await adapter.parse_document("file://test.pdf", "pdf")
        assert result["status"] == "submitted"
        assert "job_id" in result

    @pytest.mark.asyncio
    async def test_parse_document_with_options(self):
        adapter = RAGFlowAdapter()
        result = await adapter.parse_document(
            "file://scan.pdf", "pdf",
            options={"ocr": True, "vlm": True, "chunking_template": "manual"},
        )
        assert result["ocr_enabled"] is True
        assert result["vlm_enabled"] is True

    @pytest.mark.asyncio
    async def test_get_parse_result(self):
        adapter = RAGFlowAdapter()
        result = await adapter.get_parse_result("job-123")
        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_classify_document(self):
        adapter = RAGFlowAdapter()
        result = await adapter.classify_document("file://test.pdf", "pdf")
        assert "is_scanned" in result

    @pytest.mark.asyncio
    async def test_search_stub(self):
        adapter = RAGFlowAdapter()
        results = await adapter.search(_make_authz(), "test query")
        assert results == []
