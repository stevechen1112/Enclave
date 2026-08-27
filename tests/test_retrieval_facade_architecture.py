"""P1 architecture gates: RetrievalFacade + PEP + unified citations."""
from __future__ import annotations

import inspect
import ast
from pathlib import Path

import pytest

from app.platform.knowledge import KnowledgeProviderRegistry
from app.services.retrieval_facade import RetrievalFacade, get_retrieval_facade


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"


def test_facade_requires_authz():
    facade = RetrievalFacade(providers=KnowledgeProviderRegistry())
    with pytest.raises(ValueError, match="AuthorizationContext"):
        facade.search(authz=None, query="x")  # type: ignore[arg-type]


def test_facade_requires_explicit_provider_composition():
    with pytest.raises(TypeError):
        RetrievalFacade()  # type: ignore[call-arg]


def test_kb_endpoint_uses_retrieval_facade():
    from app.api.v1.endpoints import kb as kb_mod

    src = inspect.getsource(kb_mod.search_knowledge_base)
    assert "get_retrieval_facade" in src
    assert "AuthorizationContext.from_user" in src


def test_chat_orchestrator_uses_retrieval_facade():
    from app.services import chat_orchestrator as co
    from app.services import multi_step_orchestrator as mso

    # retrieve_context 委由 MultiStepOrchestrator；facade 呼叫在 orchestrator 層
    src = inspect.getsource(co.ChatOrchestrator.retrieve_context)
    assert "MultiStepOrchestrator" in src
    assert "authz_required" in src or "authz is None" in src
    orch_src = inspect.getsource(mso.MultiStepOrchestrator.run)
    assert "get_retrieval_facade" in orch_src


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


def test_retrieval_kernel_does_not_import_mka_repository():
    """Domain packs contribute through the platform registry, not core imports."""
    from app.services import retrieval_facade as rf

    src = inspect.getsource(rf)
    assert "MKARepository" not in src
    assert "app.models.mka" not in src
    assert "app.packs.mka" not in src
    assert "KnowledgeProviderRegistry" in src


def test_platform_packages_do_not_import_domain_packs():
    violations = []
    for path in (APP / "platform").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            if any(
                name.startswith(
                    ("app.packs", "app.models.mka", "app.services.mka_")
                )
                for name in names
            ):
                violations.append(
                    f"{path.relative_to(ROOT)}:{getattr(node, 'lineno', 0)}"
                )
    assert violations == []


def test_provider_candidates_are_filtered_and_fused_before_citations():
    from app.services import retrieval_facade as rf

    for method in (rf.RetrievalFacade.search, rf.RetrievalFacade.search_gateway):
        src = inspect.getsource(method)
        provider_idx = src.index("self._providers.contribute")
        visibility_idx = src.index("self._filter_gateway_visibility", provider_idx)
        fusion_idx = src.index("self._fusion.apply", visibility_idx)
        citation_idx = src.index("self._citation.build", fusion_idx)
        assert provider_idx < visibility_idx < fusion_idx < citation_idx


def test_composed_knowledge_providers_are_versioned_and_capability_declared():
    from app.composition.knowledge import build_knowledge_provider_registry

    registry = build_knowledge_provider_registry()
    assert registry.provider_keys == (
        "core.video_procedure",
        "mka.approved_knowhow",
    )


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
