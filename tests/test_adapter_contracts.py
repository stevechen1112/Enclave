"""Contract tests for mock + HTTP gateway adapters (respx for HTTP)."""
from __future__ import annotations

import uuid

import pytest
import respx
import httpx

from app.core.authorization import AuthorizationContext
from app.gateway.adapters.base import MockAdapter
from app.gateway.adapters.ragflow import RAGFlowAdapter
from app.gateway.adapters.pipeshub import PipesHubAdapter
from app.gateway.adapters.weknora import WeKnoraAdapter
from app.gateway.adapters.ragflow_http import RAGFlowHTTPAdapter
from app.gateway.adapters.pipeshub_http import PipesHubHTTPAdapter
from app.gateway.adapters.weknora_http import WeKnoraHTTPAdapter


def _authz():
    return AuthorizationContext(
        tenant_id=uuid.uuid4(),
        subject_id=uuid.uuid4(),
        is_superuser=True,
        policy_revision=1,
    )


@pytest.mark.asyncio
async def test_adapter_contract_suite_in_memory():
    """MockAdapter full contract; legacy stubs must fail-closed (no fake success)."""
    authz = _authz()
    doc_id = uuid.uuid4()

    adapter = MockAdapter(domain="document")
    caps = await adapter.capabilities()
    assert "provider" in caps
    health = await adapter.health()
    assert "status" in health
    ingest = await adapter.ingest(doc_id, 1, "file://test.pdf", "hash123", "pdf", authz)
    assert ingest.get("status") in ("submitted", "error", "skipped", "ingested")
    assert isinstance(await adapter.search(authz, "test query", top_k=5), list)
    assert isinstance(await adapter.delete("document", str(doc_id), 1, "idem-key"), dict)
    assert "converged" in await adapter.reconcile("document", str(doc_id), 1)
    assert "provider" in await adapter.export_manifest(1)

    for stub in (RAGFlowAdapter(), PipesHubAdapter(), WeKnoraAdapter()):
        assert "provider" in await stub.capabilities()
        with pytest.raises(RuntimeError):
            await stub.ingest(doc_id, 1, "file://test.pdf", "hash123", "pdf", authz)
        recon = await stub.reconcile("document", str(doc_id), 1)
        assert recon.get("converged") is False


@pytest.mark.asyncio
@respx.mock
async def test_http_adapters_contract_suite():
    authz = _authz()
    doc_id = uuid.uuid4()

    # RAGFlow
    respx.get("http://ragflow.test/api/v1/system/healthz").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    respx.post("http://ragflow.test/api/v1/retrieval").mock(
        return_value=httpx.Response(200, json={"chunks": []})
    )
    rag = RAGFlowHTTPAdapter(base_url="http://ragflow.test", api_key="k")
    assert "provider" in await rag.capabilities()
    assert (await rag.health())["status"] in ("healthy", "unhealthy")
    search = await rag.search(authz, "q", top_k=3)
    assert isinstance(search, list)
    delete = await rag.delete("document", str(doc_id), 1, "idem")
    assert isinstance(delete, dict)
    rec = await rag.reconcile("document", str(doc_id), 1)
    assert "converged" in rec
    man = await rag.export_manifest(1)
    assert "provider" in man

    # PipesHub
    respx.get("http://pipeshub.test/api/v1/health/services").mock(
        return_value=httpx.Response(
            200,
            json={"status": "healthy", "services": {"query": "healthy", "connector": "healthy"}},
        )
    )
    respx.post("http://pipeshub.test/api/v1/search").mock(
        return_value=httpx.Response(200, json={"searchResponse": {"searchResults": [], "records": []}})
    )
    pipe = PipesHubHTTPAdapter(base_url="http://pipeshub.test", api_key="k")
    assert "provider" in await pipe.capabilities()
    assert (await pipe.health())["status"] in ("healthy", "degraded", "unhealthy")
    assert isinstance(await pipe.search(authz, "q", top_k=3), list)
    assert isinstance(await pipe.delete("document", str(doc_id), 1, "idem"), dict)
    assert "converged" in await pipe.reconcile("document", str(doc_id), 1)
    assert "provider" in await pipe.export_manifest(1)

    # WeKnora
    respx.get("http://weknora.test/health").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    respx.get(url__startswith="http://weknora.test/api/v1/knowledge/search").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    wek = WeKnoraHTTPAdapter(base_url="http://weknora.test", api_key="k")
    assert "provider" in await wek.capabilities()
    assert (await wek.health())["status"] in ("healthy", "unhealthy")
    assert isinstance(await wek.search(authz, "q", top_k=3), list)
    assert isinstance(await wek.delete("document", str(doc_id), 1, "idem"), dict)
    assert "converged" in await wek.reconcile("document", str(doc_id), 1)
    assert "provider" in await wek.export_manifest(1)
