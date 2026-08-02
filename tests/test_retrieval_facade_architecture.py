"""P1 architecture gates: RetrievalFacade + PEP + unified citations."""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from app.services.retrieval_facade import RetrievalFacade, get_retrieval_facade


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"


def test_facade_requires_authz():
    facade = RetrievalFacade()
    with pytest.raises(ValueError, match="AuthorizationContext"):
        facade.search(authz=None, query="x")  # type: ignore[arg-type]


def test_kb_endpoint_uses_retrieval_facade():
    from app.api.v1.endpoints import kb as kb_mod

    src = inspect.getsource(kb_mod.search_knowledge_base)
    assert "get_retrieval_facade" in src
    assert "AuthorizationContext.from_user" in src


def test_chat_orchestrator_uses_retrieval_facade():
    from app.services import chat_orchestrator as co

    src = inspect.getsource(co.ChatOrchestrator.retrieve_context)
    assert "get_retrieval_facade" in src
    assert "authz_required" in src or "authz is None" in src


def test_unified_retriever_uses_citation_builder():
    from app.services import unified_retriever as ur

    src = inspect.getsource(ur.UnifiedRetriever.retrieve)
    assert "CitationBuilder" in src


def test_knowledge_api_modules_import_authz_or_facade():
    """Knowledge-facing API modules must reference facade or AuthorizationContext."""
    targets = [
        APP / "api" / "v1" / "endpoints" / "kb.py",
        APP / "api" / "v1" / "endpoints" / "gateway.py",
        APP / "api" / "v1" / "endpoints" / "generate.py",
        APP / "api" / "v1" / "endpoints" / "chat.py",
    ]
    for path in targets:
        text = path.read_text(encoding="utf-8")
        assert (
            "AuthorizationContext" in text
            or "get_retrieval_facade" in text
            or "GatewayRouter" in text
        ), f"{path.name} missing authz/facade wiring"


def test_no_production_stub_adapter_imports_in_factory():
    """Production adapter factory must not register stub adapters."""
    from app.gateway import adapter_factory as af

    src = inspect.getsource(af.build_projection_adapters)
    assert "ragflow.py" not in src or "RAGFlowAdapter(" not in src
    assert "stub" not in src.lower() or "stubs that fake" in src.lower()


def test_get_retrieval_facade_singleton():
    a = get_retrieval_facade()
    b = get_retrieval_facade()
    assert a is b


def test_search_gateway_uses_configured_router():
    """Facade must not construct an empty GatewayRouter()."""
    from app.services import retrieval_facade as rf

    src = inspect.getsource(rf.RetrievalFacade.search_gateway)
    assert "get_configured_gateway_router" in src
    assert "GatewayRouter()" not in src
    assert "gateway_no_adapter" in src


def test_delete_document_checks_department_acl():
    from app.api.v1.endpoints import documents as docs_mod

    src = inspect.getsource(docs_mod.delete_document)
    assert "can_access_document_by_department" in src


def test_watcher_delete_uses_revocation_service():
    from app.tasks import document_tasks as dt

    src = inspect.getsource(dt.watcher_delete_file_task)
    assert "get_document_revocation" in src
    assert "crud_document.delete" not in src


def test_watcher_ingest_clears_tombstone():
    from app.tasks import document_tasks as dt

    src = inspect.getsource(dt.watcher_ingest_file_task)
    assert "tombstoned_at = None" in src or "tombstoned_at=None" in src


def test_prod_deploy_migrates_before_up():
    text = (ROOT / ".github" / "workflows" / "deploy-production.yml").read_text(encoding="utf-8")
    stop_idx = text.find("stop web worker worker-beat")
    run_idx = text.find("alembic upgrade head")
    up_idx = text.find("up -d --no-build --remove-orphans")
    assert stop_idx != -1 and run_idx != -1 and up_idx != -1
    assert stop_idx < run_idx < up_idx
