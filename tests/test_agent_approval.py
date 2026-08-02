"""
Phase 6 — Agent, Approval, Sandbox Contract Tests
"""
import uuid
import pytest
from app.agent.react_loop import (
    ReActLoop, ToolRegistry, ToolDefinition, ToolRisk, ToolCategory,
    ApprovalGate, ApprovalRequest, AgentEvent,
)
from app.core.authorization import AuthorizationContext


def _make_authz():
    return AuthorizationContext(
        tenant_id=uuid.uuid4(),
        subject_id=uuid.uuid4(),
        role_ids=["admin"],
        policy_revision=1,
    )


class TestToolRegistry:
    """Tool Registry 測試。"""

    def test_register_and_approve(self):
        registry = ToolRegistry()
        tool = ToolDefinition(
            name="kb_search",
            description="搜尋知識庫",
            risk=ToolRisk.READ_ONLY,
            category=ToolCategory.SEARCH,
        )
        registry.register(tool)
        assert registry.get_tool("kb_search") is None  # 未核准

        registry.approve("kb_search")
        assert registry.get_tool("kb_search") is not None
        assert registry.is_allowed("kb_search") is True

    def test_revoke(self):
        registry = ToolRegistry()
        tool = ToolDefinition(name="test_tool", description="test", risk=ToolRisk.READ_ONLY)
        registry.register(tool)
        registry.approve("test_tool")
        registry.revoke("test_tool")
        assert registry.is_allowed("test_tool") is False

    def test_get_allowed_tools(self):
        registry = ToolRegistry()
        registry.register(ToolDefinition(name="t1", description="d1", risk=ToolRisk.READ_ONLY))
        registry.register(ToolDefinition(name="t2", description="d2", risk=ToolRisk.LOW_RISK_WRITE))
        registry.approve("t1")
        allowed = registry.get_allowed_tools()
        assert len(allowed) == 1
        assert allowed[0].name == "t1"

    def test_prohibited_tool_not_allowed(self):
        registry = ToolRegistry()
        tool = ToolDefinition(name="dangerous", description="bad", risk=ToolRisk.PROHIBITED)
        registry.register(tool)
        registry.approve("dangerous")
        assert registry.is_allowed("dangerous") is False
        assert registry.get_tool("dangerous") is None


class TestApprovalGate:
    """Approval Gate 測試。"""

    @pytest.mark.asyncio
    async def test_read_only_auto_approved(self):
        gate = ApprovalGate()
        tool = ToolDefinition(name="search", description="search", risk=ToolRisk.READ_ONLY)
        authz = _make_authz()
        result = await gate.check_approval(tool, authz)
        assert result is True

    @pytest.mark.asyncio
    async def test_high_risk_requires_approval(self):
        gate = ApprovalGate()
        tool = ToolDefinition(
            name="write_erp", description="寫入 ERP",
            risk=ToolRisk.HIGH_RISK_WRITE, category=ToolCategory.EXTERNAL_SYSTEM,
        )
        authz = _make_authz()
        result = await gate.check_approval(tool, authz)
        assert result is False
        assert len(gate.get_pending()) == 1

    @pytest.mark.asyncio
    async def test_prohibited_blocked(self):
        gate = ApprovalGate()
        tool = ToolDefinition(name="dangerous", description="bad", risk=ToolRisk.PROHIBITED)
        authz = _make_authz()
        result = await gate.check_approval(tool, authz)
        assert result is False

    @pytest.mark.asyncio
    async def test_approve_and_reject(self):
        gate = ApprovalGate()
        tool = ToolDefinition(
            name="write_erp", description="寫入 ERP",
            risk=ToolRisk.HIGH_RISK_WRITE, category=ToolCategory.EXTERNAL_SYSTEM,
        )
        authz = _make_authz()
        await gate.check_approval(tool, authz)
        pending = gate.get_pending()
        assert len(pending) == 1
        request_id = pending[0].request_id
        gate.approve(request_id, "admin@test.com", "approved")
        assert pending[0].status == "approved"

    @pytest.mark.asyncio
    async def test_reject(self):
        gate = ApprovalGate()
        tool = ToolDefinition(
            name="write_erp", description="寫入 ERP",
            risk=ToolRisk.HIGH_RISK_WRITE, category=ToolCategory.EXTERNAL_SYSTEM,
        )
        authz = _make_authz()
        await gate.check_approval(tool, authz)
        pending = gate.get_pending()
        gate.reject(pending[0].request_id, "admin@test.com", "too risky")
        assert pending[0].status == "rejected"


class TestReActLoop:
    """ReAct Loop 測試。"""

    @pytest.mark.asyncio
    async def test_run_produces_events(self):
        registry = ToolRegistry()
        registry.register(ToolDefinition(name="kb_search", description="search", risk=ToolRisk.READ_ONLY))
        registry.approve("kb_search")

        loop = ReActLoop(tool_registry=registry, max_iterations=3)
        authz = _make_authz()

        events = []
        async for event in loop.run("測試查詢", authz):
            events.append(event)

        assert len(events) > 0
        # 最後一個事件應為 final_answer
        assert events[-1].type == "final_answer"

    @pytest.mark.asyncio
    async def test_no_chain_of_thought_in_events(self):
        """確保事件不包含 chain-of-thought。"""
        registry = ToolRegistry()
        registry.register(ToolDefinition(name="kb_search", description="search", risk=ToolRisk.READ_ONLY))
        registry.approve("kb_search")

        loop = ReActLoop(tool_registry=registry)
        authz = _make_authz()

        async for event in loop.run("測試", authz):
            # 所有事件應有 progress_summary（可稽核摘要）
            if event.type != "final_answer":
                assert event.progress_summary is not None
            # 不應有 chain-of-thought 欄位
            assert not hasattr(event, 'chain_of_thought')
