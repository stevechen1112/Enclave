"""Phase 5-7 Integration Tests."""
import uuid, pytest, asyncio, tempfile, os
from app.core.authorization import AuthorizationContext
from app.gateway.router import GatewayRouter
from app.gateway.adapters.base import MockAdapter
from app.gateway.contracts import SearchDomain, ChunkResult
from app.services.unified_retriever import UnifiedRetriever, UnifiedRetrievalResult

def _make_authz(tenant_id=None, user_id=None, role="employee", dept_ids=None, is_superuser=False):
    return AuthorizationContext(tenant_id=tenant_id or uuid.uuid4(), subject_id=user_id or uuid.uuid4(), role_ids=[role], department_ids=dept_ids or [], is_superuser=is_superuser, policy_revision=1)

class TestUnifiedRetrieval:
    def test_retriever_initialization(self):
        router = GatewayRouter(); retriever = UnifiedRetriever(router); assert retriever.router is router
    def test_normalize_scores(self):
        router = GatewayRouter(); retriever = UnifiedRetriever(router)
        chunks = [ChunkResult(id="1", content="a", score=0.9, result_type="chunk", provider="r", provider_version="1"), ChunkResult(id="2", content="b", score=0.5, result_type="chunk", provider="w", provider_version="1"), ChunkResult(id="3", content="c", score=0.1, result_type="chunk", provider="e", provider_version="1")]
        n = retriever._normalize_scores(chunks); assert len(n) == 3; assert n[0].score == 1.0; assert n[-1].score == 0.0
    def test_deduplicate_same_doc(self):
        router = GatewayRouter(); retriever = UnifiedRetriever(router); doc_id = str(uuid.uuid4())
        chunks = [ChunkResult(id="1", content="same", score=0.9, result_type="chunk", document_id=doc_id, provider="r", provider_version="1"), ChunkResult(id="2", content="same", score=0.8, result_type="chunk", document_id=doc_id, provider="w", provider_version="1")]
        assert len(retriever._deduplicate(chunks)) == 1
    def test_deduplicate_different_doc(self):
        router = GatewayRouter(); retriever = UnifiedRetriever(router)
        chunks = [ChunkResult(id="1", content="same", score=0.9, result_type="chunk", document_id=str(uuid.uuid4()), provider="r", provider_version="1"), ChunkResult(id="2", content="same", score=0.8, result_type="chunk", document_id=str(uuid.uuid4()), provider="w", provider_version="1")]
        assert len(retriever._deduplicate(chunks)) == 2
    def test_build_citations(self):
        router = GatewayRouter(); retriever = UnifiedRetriever(router); doc_id = str(uuid.uuid4())
        c = retriever._build_citations([ChunkResult(id="c1", content="c", score=0.9, result_type="chunk", document_id=doc_id, provider="r", provider_version="1")])
        assert len(c) == 1; assert c[0].artifact_id == "c1"
    def test_context_parts(self):
        doc_id = str(uuid.uuid4()); r = UnifiedRetrievalResult(results=[ChunkResult(id="1", content="內容A", score=0.9, result_type="chunk", document_id=doc_id, provider="r", provider_version="1")], citations=[], audit_trail=None, total_results=1, deduped_count=1)
        assert "內容A" in r.to_context_parts()[0]
    def test_sources_list(self):
        doc_id = str(uuid.uuid4()); r = UnifiedRetrievalResult(results=[ChunkResult(id="1", content="A"*50, score=0.9, result_type="chunk", document_id=doc_id, provider="r", provider_version="1")], citations=[], audit_trail=None, total_results=1, deduped_count=1)
        assert r.to_sources_list()[0]["id"] == "1"
    @pytest.mark.asyncio
    async def test_retrieve_mock(self):
        router = GatewayRouter(); router.register_adapter("document", MockAdapter(domain="document")); router.register_adapter("wiki", MockAdapter(domain="wiki"))
        retriever = UnifiedRetriever(router); authz = _make_authz(is_superuser=True)
        result = await retriever.retrieve(authz=authz, query="test", top_k=10, domain=SearchDomain.HYBRID)
        assert result is not None; assert result.total_results >= 0

class TestAgentApproval:
    def test_register_approve_revoke(self):
        from app.agent.react_loop import ToolRegistry, ToolDefinition, ToolRisk, ToolCategory
        registry = ToolRegistry(); tool = ToolDefinition(name="kb_search", description="搜尋", risk=ToolRisk.READ_ONLY, category=ToolCategory.SEARCH)
        registry.register(tool); assert "kb_search" in registry._tools
        registry.approve("kb_search"); assert any(t.name == "kb_search" for t in registry.get_allowed_tools())
        registry.revoke("kb_search"); assert not any(t.name == "kb_search" for t in registry.get_allowed_tools())
    @pytest.mark.asyncio
    async def test_read_only_auto(self):
        from app.agent.react_loop import ApprovalGate, ToolDefinition, ToolRisk, ToolCategory
        gate = ApprovalGate(); tool = ToolDefinition(name="kb_search", description="搜尋", risk=ToolRisk.READ_ONLY, category=ToolCategory.SEARCH)
        assert await gate.check_approval(tool, _make_authz()) is True
    @pytest.mark.asyncio
    async def test_high_risk_requires_approval(self):
        from app.agent.react_loop import ApprovalGate, ToolDefinition, ToolRisk, ToolCategory
        gate = ApprovalGate(); tool = ToolDefinition(name="delete", description="刪除", risk=ToolRisk.HIGH_RISK_WRITE, category=ToolCategory.DOCUMENT)
        assert await gate.check_approval(tool, _make_authz()) is False
    @pytest.mark.asyncio
    async def test_prohibited_blocked(self):
        from app.agent.react_loop import ApprovalGate, ToolDefinition, ToolRisk, ToolCategory
        gate = ApprovalGate(); tool = ToolDefinition(name="dangerous", description="危險", risk=ToolRisk.PROHIBITED, category=ToolCategory.CODE_EXECUTION)
        assert await gate.check_approval(tool, _make_authz()) is False
    @pytest.mark.asyncio
    async def test_react_loop_events(self):
        from app.agent.react_loop import ReActLoop, ToolRegistry, ToolDefinition, ToolRisk, ToolCategory
        registry = ToolRegistry(); registry.register(ToolDefinition(name="kb_search", description="搜尋", risk=ToolRisk.READ_ONLY, category=ToolCategory.SEARCH))
        registry.approve("kb_search"); loop = ReActLoop(tool_registry=registry, max_iterations=2)
        events = [e async for e in loop.run(user_query="測試", authz=_make_authz())]; assert len(events) > 0
    @pytest.mark.asyncio
    async def test_no_cot_in_events(self):
        from app.agent.react_loop import ReActLoop, ToolRegistry, ToolDefinition, ToolRisk, ToolCategory
        registry = ToolRegistry(); registry.register(ToolDefinition(name="kb_search", description="搜尋", risk=ToolRisk.READ_ONLY, category=ToolCategory.SEARCH))
        registry.approve("kb_search"); loop = ReActLoop(tool_registry=registry, max_iterations=1)
        async for event in loop.run(user_query="查詢", authz=_make_authz()):
            assert "cot" not in str(event).lower(); assert "reasoning" not in str(event).lower()

class TestDeploymentProfile:
    def test_profiles_exist(self):
        from app.services.deployment import PROFILES, DeploymentProfile
        for p in DeploymentProfile: assert p in PROFILES
    def test_lite_config(self):
        from app.services.deployment import PROFILES, DeploymentProfile
        cfg = PROFILES[DeploymentProfile.LITE]; assert cfg.hardware.cpu_cores == 4; assert cfg.hardware.ram_gb == 8; assert "enclave" in cfg.services
    def test_standard_config(self):
        from app.services.deployment import PROFILES, DeploymentProfile
        cfg = PROFILES[DeploymentProfile.STANDARD]; assert cfg.hardware.gpu_required is True; assert "ragflow" in cfg.services
    def test_enterprise_config(self):
        from app.services.deployment import PROFILES, DeploymentProfile
        cfg = PROFILES[DeploymentProfile.ENTERPRISE]; assert cfg.hardware.cpu_cores == 16; assert "minio" in cfg.services
    def test_preflight(self):
        from app.services.deployment import run_preflight, DeploymentProfile
        r = run_preflight(DeploymentProfile.LITE); assert hasattr(r, 'passed')
    def test_support_bundle(self):
        from app.services.deployment import generate_support_bundle
        with tempfile.TemporaryDirectory() as d:
            path = generate_support_bundle(d); assert os.path.exists(path)
            import json
            with open(path) as f: bundle = json.load(f)
            assert "enclave_version" in bundle
    def test_version_matrix(self):
        from app.services.deployment import VERSION_MATRIX
        assert "enclave" in VERSION_MATRIX; assert "upstream" in VERSION_MATRIX; assert "ragflow" in VERSION_MATRIX["upstream"]

class TestFullIntegration:
    @pytest.mark.asyncio
    async def test_full_retrieval(self):
        router = GatewayRouter(); router.register_adapter("document", MockAdapter(domain="document")); router.register_adapter("wiki", MockAdapter(domain="wiki")); router.register_adapter("graph", MockAdapter(domain="graph"))
        retriever = UnifiedRetriever(router); authz = _make_authz(is_superuser=True)
        result = await retriever.retrieve(authz=authz, query="企業知識庫查詢", top_k=10, domain=SearchDomain.HYBRID)
        assert result is not None; assert hasattr(result, 'results')
    @pytest.mark.asyncio
    async def test_agent_approval_flow(self):
        from app.agent.react_loop import ToolRegistry, ToolDefinition, ToolRisk, ToolCategory, ApprovalGate
        registry = ToolRegistry(); gate = ApprovalGate()
        for t in [ToolDefinition(name="search", description="搜尋", risk=ToolRisk.READ_ONLY, category=ToolCategory.SEARCH), ToolDefinition(name="export", description="匯出", risk=ToolRisk.LOW_RISK_WRITE, category=ToolCategory.DOCUMENT), ToolDefinition(name="delete", description="刪除", risk=ToolRisk.HIGH_RISK_WRITE, category=ToolCategory.DOCUMENT)]:
            registry.register(t)
        registry.approve("search"); registry.approve("export"); authz = _make_authz()
        assert await gate.check_approval(registry._tools["search"], authz) is True
        assert await gate.check_approval(registry._tools["export"], authz) is True
        assert await gate.check_approval(registry._tools["delete"], authz) is False
    def test_profiles_complete(self):
        from app.services.deployment import PROFILES, DeploymentProfile
        for p in DeploymentProfile:
            cfg = PROFILES[p]; assert len(cfg.services) > 0; assert cfg.hardware.cpu_cores > 0
