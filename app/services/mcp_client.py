"""
P3-3：MCP Client + Allowlist + ApprovalGate。

稽核文件 §8.2 P2：
- MCP client＋allowlist＋ApprovalGate
- 大量文件仍走 HTTP／connector，不走 MCP

與 P1-3 ApprovalStateMachine 整合：
- read-only tool 直接允許
- mutating tool 霈 approval（AGENT_APPROVAL_REQUIRE_FOR_MUTATING）
- allowlist 限制可連的 MCP server
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from uuid import UUID

logger = logging.getLogger(__name__)


@dataclass
class MCPServerConfig:
    """外部 MCP server 設定。"""
    name: str
    url: str
    auth_token: str = ""
    allowed_tools: List[str] = field(default_factory=list)  # 空 = 全部允許
    blocked_tools: List[str] = field(default_factory=list)
    timeout: int = 30


class MCPClient:
    """MCP Client — 連接外部 MCP server，執行工具。

    安全設計：
    1. Allowlist — 只連設定中的 server
    2. Tool allowlist — 只執行允許的工具
    3. ApprovalGate — mutating tool 需 approval
    4. AuthorizationContext 必須傳遞
    """

    def __init__(self, servers: Optional[List[MCPServerConfig]] = None):
        self._servers: Dict[str, MCPServerConfig] = {}
        if servers:
            for s in servers:
                self._servers[s.name] = s

    def add_server(self, config: MCPServerConfig) -> None:
        self._servers[config.name] = config
        logger.info(f"MCP server added: {config.name} ({config.url})")

    def remove_server(self, name: str) -> None:
        self._servers.pop(name, None)

    def list_servers(self) -> List[str]:
        return sorted(self._servers.keys())

    def is_allowed_server(self, name: str) -> bool:
        """檢查 server 是否在 allowlist 中。"""
        from app.config import settings
        if not settings.MCP_CLIENT_ENABLED:
            return False

        # 檢查全域 allowlist
        global_allowlist = settings.MCP_CLIENT_ALLOWLIST
        if global_allowlist:
            allowed = [s.strip() for s in global_allowlist.split(",")]
            if name not in allowed:
                return False

        return name in self._servers

    def is_tool_allowed(self, server_name: str, tool_name: str) -> bool:
        """檢查工具是否被允許。"""
        server = self._servers.get(server_name)
        if server is None:
            return False

        # blocked 優先
        if tool_name in server.blocked_tools:
            return False

        # 若有 allowed_tools 限制，檢查是否在列表中
        if server.allowed_tools and tool_name not in server.allowed_tools:
            return False

        return True

    def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: Dict[str, Any],
        authz: Any,
    ) -> Dict[str, Any]:
        """呼叫外部 MCP server 的工具。

        Args:
            server_name: MCP server 名稱
            tool_name: 工具名稱
            arguments: 工具參數
            authz: AuthorizationContext（必須）

        Returns:
            工具執行結果

        Raises:
            ValueError: server 不在 allowlist 或工具不允許
            RuntimeError: MCP client 未啟用
        """
        if authz is None:
            raise ValueError("AuthorizationContext is required")

        from app.config import settings
        if not settings.MCP_CLIENT_ENABLED:
            raise RuntimeError("MCP_CLIENT_ENABLED is false")

        # 1. Server allowlist
        if not self.is_allowed_server(server_name):
            raise ValueError(f"MCP server not in allowlist: {server_name}")

        # 2. Tool allowlist
        if not self.is_tool_allowed(server_name, tool_name):
            raise ValueError(f"Tool not allowed: {server_name}/{tool_name}")

        # 3. ApprovalGate for mutating tools
        is_mutating = self._is_mutating_tool(server_name, tool_name)
        if is_mutating and settings.MCP_CLIENT_REQUIRE_APPROVAL:
            approval = self._check_approval(server_name, tool_name, arguments, authz)
            if not approval["approved"]:
                return {
                    "status": "approval_required",
                    "approval_request_id": approval.get("request_id"),
                    "message": f"Tool {tool_name} requires approval",
                }

        # 4. 執行工具
        return self._execute_remote_tool(server_name, tool_name, arguments, authz)

    def _is_mutating_tool(self, server_name: str, tool_name: str) -> bool:
        """判斷工具是否為 mutating（用 word boundary 避免誤判）。"""
        import re
        mutating_keywords = [
            "create", "update", "delete", "upload", "modify", "write",
            "remove", "submit", "approve", "reject",
        ]
        tool_lower = tool_name.lower()
        for kw in mutating_keywords:
            # 用 word boundary（含下劃線/連字號分隔）
            if re.search(rf'(?:^|[_\-]){kw}(?:$|[_\-])', tool_lower):
                return True
        return False

    def _check_approval(
        self,
        server_name: str,
        tool_name: str,
        arguments: Dict[str, Any],
        authz: Any,
    ) -> Dict[str, Any]:
        """檢查是否已有 approval 或建立新 approval request。

        冪等設計：先搜尋是否已有同 tool+actor 的 approved request，
        若有則直接通過；否則建立新 pending request。
        """
        try:
            from app.services.approval_state import get_approval_state_machine
            sm = get_approval_state_machine()

            # 先檢查是否已有已核准的 request（冪等）
            full_tool_name = f"mcp:{server_name}/{tool_name}"
            actor_id = getattr(authz, "user_id", UUID(int=0))

            for ctx in sm._pending.values():
                if (
                    ctx.tool_name == full_tool_name
                    and ctx.actor_id == actor_id
                    and ctx.state.value == "approved"
                ):
                    return {"approved": True, "request_id": str(ctx.request_id)}

            # 建立新 approval request
            ctx = sm.create_request(
                tool_name=full_tool_name,
                tool_risk="high_risk_write",
                actor_id=actor_id,
                actor_name=getattr(authz, "subject_id", "unknown"),
                action_summary=f"Execute MCP tool {server_name}/{tool_name}",
                tool_args=arguments,
                target_system=server_name,
            )

            return {"approved": False, "request_id": str(ctx.request_id)}

        except Exception as exc:
            logger.error(f"Approval check failed: {exc}")
            return {"approved": False, "error": str(exc)}

    def _execute_remote_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: Dict[str, Any],
        authz: Any,
    ) -> Dict[str, Any]:
        """執行遠端 MCP server 的工具。"""
        server = self._servers.get(server_name)
        if server is None:
            raise ValueError(f"Server not found: {server_name}")

        try:
            import httpx

            headers = {"Content-Type": "application/json"}
            if server.auth_token:
                headers["Authorization"] = f"Bearer {server.auth_token}"

            # 傳遞 AuthorizationContext（不繞過 PEP）
            auth_context = {
                "subject_id": str(getattr(authz, "subject_id", "")),
                "tenant_id": str(getattr(authz, "tenant_id", "")),
                "department_id": str(getattr(authz, "department_id", "") or ""),
            }
            payload = {
                "tool": tool_name,
                "arguments": arguments,
                "authz": auth_context,
            }

            with httpx.Client(timeout=server.timeout) as client:
                resp = client.post(
                    f"{server.url}/mcp/tools/{tool_name}",
                    json=payload,
                    headers=headers,
                )

                if resp.status_code == 200:
                    return resp.json()
                else:
                    return {
                        "status": "error",
                        "error": f"HTTP {resp.status_code}: {resp.text[:500]}",
                    }

        except Exception as exc:
            logger.error(f"MCP remote tool execution failed: {exc}")
            return {"status": "error", "error": str(exc)}


# ── 單例 ──

_client: Optional[MCPClient] = None


def get_mcp_client() -> MCPClient:
    global _client
    if _client is None:
        _client = MCPClient()
    return _client