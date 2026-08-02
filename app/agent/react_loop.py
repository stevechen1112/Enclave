"""
Phase 6 — Agent Runtime (ReAct Loop)

ReAct (Reasoning + Acting) 執行循環。
Agent 工具預設拒絕；每個工具需聲明 read/write、risk level、scope、timeout、資料分類與審批政策。

不向前端輸出模型私有 chain-of-thought；僅輸出可解釋的進度摘要、工具動作與結果。
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Dict, List, Optional
from uuid import UUID

from app.core.authorization import AuthorizationContext

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
#  Tool Risk Classification
# ═══════════════════════════════════════════════════════════════════════════════

class ToolRisk(str, Enum):
    READ_ONLY = "read_only"
    LOW_RISK_WRITE = "low_risk_write"
    HIGH_RISK_WRITE = "high_risk_write"
    PROHIBITED = "prohibited"


class ToolCategory(str, Enum):
    SEARCH = "search"
    DOCUMENT = "document"
    CONNECTOR = "connector"
    WIKI = "wiki"
    EXTERNAL_SYSTEM = "external_system"
    CODE_EXECUTION = "code_execution"


@dataclass
class ToolDefinition:
    """工具定義 — 每個 Agent 工具必須聲明以下屬性。"""
    name: str
    description: str
    risk: ToolRisk = ToolRisk.READ_ONLY
    category: ToolCategory = ToolCategory.SEARCH
    requires_approval: bool = False
    timeout_seconds: int = 30
    max_retries: int = 1
    parameters: Dict[str, Any] = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════════════
#  Agent Events (SSE)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class AgentEvent:
    """Agent 執行事件 — 透過 SSE 推送給前端。"""
    type: str  # status | tool_call | tool_result | approval_required | final_answer | error
    content: str = ""
    tool_name: Optional[str] = None
    tool_args: Optional[Dict[str, Any]] = None
    tool_result: Optional[Any] = None
    progress_summary: Optional[str] = None  # 可稽核的進度摘要（非 chain-of-thought）


# ═══════════════════════════════════════════════════════════════════════════════
#  ReAct Loop
# ═══════════════════════════════════════════════════════════════════════════════

class ReActLoop:
    """
    ReAct 執行循環。

    流程：Thought → Action → Observation → ... → Final Answer

    終止條件：
      - LLM 輸出 Final Answer（無 tool_call）
      - 達到 max_iterations
      - 觸發 Human-in-the-Loop 審批（暫停等待）
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
        max_iterations: int = 10,
        approval_gate: Optional[ApprovalGate] = None,
    ):
        self.tool_registry = tool_registry
        self.max_iterations = max_iterations
        self.approval_gate = approval_gate

    async def run(
        self,
        user_query: str,
        authz: AuthorizationContext,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> AsyncIterator[AgentEvent]:
        """
        執行 ReAct Loop，yield 每個步驟的事件。
        使用已核准工具執行檢索，不輸出 chain-of-thought。
        """
        yield AgentEvent(
            type="status",
            content="正在分析問題...",
            progress_summary="開始分析使用者問題",
        )

        allowed_tools = self.tool_registry.get_allowed_tools()
        tool_results: List[Dict[str, Any]] = []

        for tool in allowed_tools:
            if tool.risk == ToolRisk.PROHIBITED:
                continue

            if self.approval_gate:
                approved = await self.approval_gate.check_approval(tool, authz)
                if not approved:
                    yield AgentEvent(
                        type="approval_required",
                        tool_name=tool.name,
                        progress_summary=f"工具 {tool.name} 需要人工審批",
                    )
                    return

            yield AgentEvent(
                type="tool_call",
                tool_name=tool.name,
                tool_args={"query": user_query},
                progress_summary=f"執行工具：{tool.name}",
            )

            result = await self._execute_tool(tool, user_query, authz)
            tool_results.append({"tool": tool.name, "result": result})

            yield AgentEvent(
                type="tool_result",
                tool_name=tool.name,
                tool_result=result,
                progress_summary=f"工具 {tool.name} 完成",
            )

        answer = self._compose_answer(user_query, tool_results)
        yield AgentEvent(
            type="final_answer",
            content=answer,
            progress_summary="生成最終回答",
        )

    async def _execute_tool(
        self,
        tool: ToolDefinition,
        query: str,
        authz: AuthorizationContext,
    ) -> Dict[str, Any]:
        if tool.name == "kb_search":
            from app.services.retrieval_facade import get_retrieval_facade
            loop = asyncio.get_event_loop()
            retrieved = await loop.run_in_executor(
                None,
                lambda: get_retrieval_facade().search(
                    authz=authz,
                    query=query,
                    top_k=5,
                ),
            )
            return {
                "results_count": retrieved.total,
                "results": retrieved.results[:3],
                "citations": [
                    {
                        "citation_id": c.citation_id,
                        "document_id": str(c.canonical_document_id),
                        "revision": c.document_revision,
                    }
                    for c in retrieved.citations[:3]
                ],
            }

        if tool.name == "document_list":
            from app.db.session import SessionLocal
            from app.models.document import Document
            from sqlalchemy import or_
            db = SessionLocal()
            try:
                q = (
                    db.query(Document)
                    .filter(
                        Document.tenant_id == authz.tenant_id,
                        Document.tombstoned_at.is_(None),
                        Document.status == "completed",
                    )
                )
                if not authz.is_superuser:
                    if authz.department_ids:
                        q = q.filter(
                            or_(
                                Document.department_id.is_(None),
                                Document.department_id.in_(authz.department_ids),
                            )
                        )
                    else:
                        q = q.filter(Document.department_id.is_(None))
                    q = q.filter(Document.source_system.is_(None))
                docs = q.limit(10).all()
                return {"document_count": len(docs)}
            finally:
                db.close()

        return {"status": "noop", "tool": tool.name}

    def _compose_answer(self, query: str, tool_results: List[Dict[str, Any]]) -> str:
        if not tool_results:
            return f"根據目前政策，無法使用任何已核准工具處理「{query[:80]}」。"

        kb_result = next((t for t in tool_results if t["tool"] == "kb_search"), None)
        if kb_result and kb_result["result"].get("results_count", 0) > 0:
            count = kb_result["result"]["results_count"]
            return f"根據知識庫搜尋結果（{count} 筆相關文件），以下是關於「{query[:50]}」的回答摘要。"

        return f"已執行 {len(tool_results)} 個工具，但知識庫中沒有足夠資料回答「{query[:50]}」。"


# ═══════════════════════════════════════════════════════════════════════════════
#  Tool Registry
# ═══════════════════════════════════════════════════════════════════════════════

class ToolRegistry:
    """
    Agent 工具註冊中心。

    工具動態發現不等於動態信任；新工具需管理員核准後才能進 allowlist。
    """

    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}
        self._allowlist: set = set()

    def register(self, tool: ToolDefinition):
        """註冊工具定義。"""
        self._tools[tool.name] = tool

    def approve(self, tool_name: str):
        """管理員核准工具進入 allowlist。prohibited 永遠不可核准。"""
        tool = self._tools.get(tool_name)
        if not tool:
            return
        if tool.risk == ToolRisk.PROHIBITED:
            logger.warning("Refusing to approve prohibited tool: %s", tool_name)
            return
        self._allowlist.add(tool_name)

    def revoke(self, tool_name: str):
        """撤銷工具核准。"""
        self._allowlist.discard(tool_name)

    def get_allowed_tools(self) -> List[ToolDefinition]:
        """取得所有已核准且非 prohibited 的工具。"""
        out = []
        for name in self._allowlist:
            tool = self._tools.get(name)
            if tool and tool.risk != ToolRisk.PROHIBITED:
                out.append(tool)
        return out

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        """取得工具定義（僅已核准且非 prohibited）。"""
        if name not in self._allowlist:
            return None
        tool = self._tools.get(name)
        if tool and tool.risk == ToolRisk.PROHIBITED:
            return None
        return tool

    def is_allowed(self, name: str) -> bool:
        tool = self._tools.get(name)
        if not tool or tool.risk == ToolRisk.PROHIBITED:
            return False
        return name in self._allowlist


# ═══════════════════════════════════════════════════════════════════════════════
#  Approval Gate
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ApprovalRequest:
    """審批請求。"""
    request_id: str
    tool_name: str
    tool_risk: ToolRisk
    actor_id: UUID
    actor_name: str
    action_summary: str
    target_system: str
    impact_scope: str
    policy_snapshot: Dict[str, Any] = field(default_factory=dict)
    status: str = "pending"  # pending | approved | rejected
    approved_by: Optional[str] = None
    approved_at: Optional[float] = None
    reason: Optional[str] = None


class ApprovalGate:
    """
    審批閘門。

    審批服務失效時寫入工具 fail closed。
    """

    def __init__(self, default_timeout_hours: int = 24, escalation_hours: int = 48):
        self.default_timeout_hours = default_timeout_hours
        self.escalation_hours = escalation_hours
        self._pending: Dict[str, ApprovalRequest] = {}

    async def check_approval(self, tool: ToolDefinition, authz: AuthorizationContext) -> bool:
        """
        檢查工具是否需要審批。

        - read_only：依政策直接執行
        - low_risk_write：可按客戶政策自動或審批
        - high_risk_write：必須人工審批
        - prohibited：不得執行
        """
        if tool.risk == ToolRisk.PROHIBITED:
            logger.warning(f"Prohibited tool blocked: {tool.name}")
            return False

        if tool.risk == ToolRisk.READ_ONLY:
            return True

        if tool.risk == ToolRisk.HIGH_RISK_WRITE:
            if self._has_db_approval(tool.name, authz.subject_id, authz.tenant_id):
                return True
            req = ApprovalRequest(
                request_id=f"apr-{uuid.uuid4().hex[:12]}",
                tool_name=tool.name,
                tool_risk=tool.risk,
                actor_id=authz.subject_id,
                actor_name=str(authz.subject_id)[:8],
                action_summary=f"執行 {tool.name}",
                target_system=tool.category.value,
                impact_scope="待評估",
                policy_snapshot={"policy_revision": authz.policy_revision},
            )
            self._pending[req.request_id] = req
            self._persist_request(req, authz)
            return False  # 等待審批

        return True  # low_risk_write 預設允許（可配置）

    def _has_db_approval(self, tool_name: str, actor_id: UUID, tenant_id: UUID) -> bool:
        try:
            from app.db.session import SessionLocal
            from app.models.agent_approval import AgentApprovalRequest as ApprovalModel
            db = SessionLocal()
            try:
                row = (
                    db.query(ApprovalModel)
                    .filter(
                        ApprovalModel.tenant_id == tenant_id,
                        ApprovalModel.actor_id == actor_id,
                        ApprovalModel.tool_name == tool_name,
                        ApprovalModel.status == "approved",
                    )
                    .order_by(ApprovalModel.approved_at.desc())
                    .first()
                )
                return row is not None
            finally:
                db.close()
        except Exception as exc:
            logger.warning("Approval DB check failed, fail closed: %s", exc)
            return False

    def _persist_request(self, req: ApprovalRequest, authz: AuthorizationContext):
        try:
            from app.db.session import SessionLocal
            from app.models.agent_approval import AgentApprovalRequest as ApprovalModel
            db = SessionLocal()
            try:
                db.add(ApprovalModel(
                    tenant_id=authz.tenant_id,
                    actor_id=authz.subject_id,
                    tool_name=req.tool_name,
                    tool_risk=req.tool_risk.value if hasattr(req.tool_risk, "value") else str(req.tool_risk),
                    tool_category=req.target_system,
                    action_summary=req.action_summary,
                    target_system=req.target_system,
                    impact_scope=req.impact_scope,
                    policy_snapshot=req.policy_snapshot,
                    status="pending",
                ))
                db.commit()
            finally:
                db.close()
        except Exception as exc:
            logger.warning("Failed to persist approval request: %s", exc)

    def approve(self, request_id: str, approver: str, reason: str = ""):
        """審批通過。"""
        req = self._pending.get(request_id)
        if req:
            req.status = "approved"
            req.approved_by = approver
            req.approved_at = time.time()
            req.reason = reason

    def reject(self, request_id: str, approver: str, reason: str):
        """審批拒絕。"""
        req = self._pending.get(request_id)
        if req:
            req.status = "rejected"
            req.approved_by = approver
            req.approved_at = time.time()
            req.reason = reason

    def get_pending(self) -> List[ApprovalRequest]:
        """取得所有待審批請求。"""
        return [r for r in self._pending.values() if r.status == "pending"]
