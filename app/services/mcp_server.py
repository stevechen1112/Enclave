"""
P3-2：Read-only FastMCP Server — 借鑑 OpenRAG src/mcp_http/server.py。

稽核文件 §8.2 P1：
- 可建立 read-only FastMCP server
- OpenAPI endpoint 自動暴露
- auth header 處理
- read-only search／chat tools
- multipart ingest 明確排除

Enclave 的 FastMCP server 只暴露 read-only 檢索與問答工具，
不暴露任何 mutating 操作（上傳、刪除、修改）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class MCPToolDef:
    """MCP 工具定義。"""
    name: str
    description: str
    input_schema: Dict[str, Any] = field(default_factory=dict)
    read_only: bool = True  # FastMCP server 只暴露 read-only


@dataclass
class MCPToolResult:
    """MCP 工具執行結果。"""
    content: str = ""
    error: str = ""
    is_error: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "content": self.content,
            "error": self.error,
            "is_error": self.is_error,
        }


class ReadOnlyFastMCPServer:
    """Read-only FastMCP Server。

    只暴露 read-only 檢索與問答工具：
    - search: 知識庫檢索
    - chat: 問答（read-only，不建立對話）
    - catalog: 文件目錄查詢
    - health: 健康檢查

    明確排除：
    - 上傳 / 刪除 / 修改文件
    - 連接器同步
    - Wiki 編輯
    - 任何 mutating 操作
    """

    def __init__(self):
        self._tools: Dict[str, MCPToolDef] = {}
        self._register_default_tools()

    def _register_default_tools(self) -> None:
        """註冊 read-only 工具。"""
        self._tools["search"] = MCPToolDef(
            name="search",
            description="Search the knowledge base for relevant chunks. Read-only.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "top_k": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
                },
                "required": ["query"],
            },
        )
        self._tools["chat"] = MCPToolDef(
            name="chat",
            description="Retrieve relevant chunks for a question (read-only, does not generate an answer). Use for evidence retrieval only.",
            input_schema={
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "Question to retrieve evidence for"},
                    "top_k": {"type": "integer", "default": 5},
                },
                "required": ["question"],
            },
        )
        self._tools["catalog"] = MCPToolDef(
            name="catalog",
            description="List available documents in the knowledge base. Read-only.",
            input_schema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 50},
                    "query": {"type": "string", "description": "Optional filter query"},
                },
            },
        )
        self._tools["health"] = MCPToolDef(
            name="health",
            description="Check system health. Read-only.",
            input_schema={"type": "object", "properties": {}},
        )

    def list_tools(self) -> List[MCPToolDef]:
        """列出所有可用工具。"""
        return list(self._tools.values())

    def get_tool(self, name: str) -> Optional[MCPToolDef]:
        return self._tools.get(name)

    def call_tool(
        self,
        name: str,
        arguments: Dict[str, Any],
        authz: Any,  # AuthorizationContext
    ) -> MCPToolResult:
        """執行工具（read-only）。

        Args:
            name: 工具名稱
            arguments: 工具參數
            authz: AuthorizationContext（必須，不繞過 PEP）

        Returns:
            MCPToolResult
        """
        if authz is None:
            return MCPToolResult(error="AuthorizationContext is required", is_error=True)

        tool = self._tools.get(name)
        if tool is None:
            return MCPToolResult(error=f"Unknown tool: {name}", is_error=True)

        if not tool.read_only:
            return MCPToolResult(error=f"Tool {name} is not read-only", is_error=True)

        try:
            if name == "search":
                return self._execute_search(arguments, authz)
            elif name == "chat":
                return self._execute_chat(arguments, authz)
            elif name == "catalog":
                return self._execute_catalog(arguments, authz)
            elif name == "health":
                return self._execute_health(arguments, authz)
            else:
                return MCPToolResult(error=f"Tool not implemented: {name}", is_error=True)
        except Exception as exc:
            logger.error(f"MCP tool {name} failed: {exc}")
            return MCPToolResult(error=str(exc), is_error=True)

    def _execute_search(self, args: Dict[str, Any], authz: Any) -> MCPToolResult:
        """執行知識庫檢索。"""
        query = args.get("query", "")
        top_k = args.get("top_k", 5)

        if not query:
            return MCPToolResult(error="query is required", is_error=True)

        from app.services.retrieval_facade import get_retrieval_facade
        facade = get_retrieval_facade()
        result = facade.search(authz=authz, query=query, top_k=top_k)

        # 格式化結果
        chunks_text = "\n\n".join(
            f"[{i+1}] (doc:{r.get('document_id', '')[:8]}) "
            f"score={r.get('score', 0):.3f}\n{r.get('content', '')[:500]}"
            for i, r in enumerate(result.results)
        )

        return MCPToolResult(content=chunks_text or "No results found")

    def _execute_chat(self, args: Dict[str, Any], authz: Any) -> MCPToolResult:
        """執行問答（read-only，不建立對話）。"""
        question = args.get("question", "")
        top_k = args.get("top_k", 5)

        if not question:
            return MCPToolResult(error="question is required", is_error=True)

        from app.services.retrieval_facade import get_retrieval_facade
        facade = get_retrieval_facade()
        result = facade.search(authz=authz, query=question, top_k=top_k)

        # 回傳檢索結果 + context parts（不生成答案，只提供證據）
        context_parts = result.to_context_parts()
        return MCPToolResult(
            content=f"Retrieved {len(result.results)} chunks:\n\n" + "\n\n".join(context_parts)
        )

    def _execute_catalog(self, args: Dict[str, Any], authz: Any) -> MCPToolResult:
        """執行文件目錄查詢。"""
        limit = args.get("limit", 50)
        query = args.get("query")

        from app.services.catalog_retrieval import get_catalog_retriever
        retriever = get_catalog_retriever()
        hits = retriever.search_catalog(authz=authz, query=query or "", top_k=limit)

        catalog_text = "\n".join(
            f"- {h.filename} (id: {h.document_id})"
            for h in hits
        )

        return MCPToolResult(content=catalog_text or "No documents found")

    def _execute_health(self, args: Dict[str, Any], authz: Any) -> MCPToolResult:
        """健康檢查。"""
        return MCPToolResult(content='{"status": "ok", "tools": ["search", "chat", "catalog", "health"]}')

    def to_openapi_schema(self) -> Dict[str, Any]:
        """產生 OpenAPI schema（供 MCP endpoint 自動暴露）。"""
        paths = {}
        for tool in self._tools.values():
            paths[f"/mcp/tools/{tool.name}"] = {
                "post": {
                    "summary": tool.description,
                    "requestBody": {
                        "content": {
                            "application/json": {"schema": tool.input_schema}
                        }
                    },
                }
            }
        return {
            "openapi": "3.0.0",
            "info": {
                "title": "Enclave Read-only MCP Server",
                "version": "1.0",
                "description": "Read-only knowledge retrieval tools. No mutating operations.",
            },
            "paths": paths,
        }


# ── 單例 ──

_server: Optional[ReadOnlyFastMCPServer] = None


def get_mcp_server() -> ReadOnlyFastMCPServer:
    global _server
    if _server is None:
        _server = ReadOnlyFastMCPServer()
    return _server