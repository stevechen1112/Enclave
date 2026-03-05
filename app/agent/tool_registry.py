"""
Phase 10 — Agent 工具框架 (Tool Registry)  [P10-4 實作]

定義 LLM 可呼叫的工具介面規範，支援 OpenAI Function Calling 格式。

設計原則：
  - Tool 抽象基類：標準化工具的 name / description / parameters / execute()
  - ToolRegistry：全域單例，管理所有已註冊工具
  - 內建工具：KBSearchTool（知識庫搜尋）、DocumentListTool（文件列舉）

使用流程：
  1. 繼承 Tool 實作自訂工具
  2. 呼叫 registry.register(MyTool()) 註冊
  3. 呼叫 registry.list_openai_functions() 取得 tools 清單傳給 LLM
  4. LLM 回傳 tool_call 後，呼叫 registry.call(name, **args) 執行工具
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from uuid import UUID

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# 基礎型別定義
# ─────────────────────────────────────────────────────────────

@dataclass
class ToolParam:
    """描述工具的單一輸入參數。"""
    name: str
    type: str                           # "string" | "integer" | "number" | "boolean" | "array" | "object"
    description: str
    required: bool = True
    enum: Optional[List[str]] = None    # 限制可選值
    default: Any = None                 # 選填參數的預設值


@dataclass
class ToolResult:
    """工具執行結果。"""
    success: bool
    data: Any = None                    # 成功時的回傳資料（任意可 JSON 序列化的結構）
    error: Optional[str] = None         # 失敗時的錯誤訊息
    metadata: Dict[str, Any] = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────
# Tool 抽象基類
# ─────────────────────────────────────────────────────────────

class Tool(ABC):
    """
    Agent 工具基類。

    子類必須定義：
      name        — 工具唯一識別碼（英數底線，LLM function_call 中使用）
      description — 工具描述（LLM 依此決定何時呼叫此工具）
      parameters  — 輸入參數清單

    子類必須實作：
      execute(**kwargs) — 實際執行邏輯，回傳 ToolResult
    """

    name: str
    description: str
    parameters: List[ToolParam]

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """執行工具，kwargs 對應 parameters 中定義的參數。"""
        ...

    def to_openai_function(self) -> Dict[str, Any]:
        """
        生成 OpenAI Function Calling 格式的工具描述。

        回傳值可直接放入 client.chat.completions.create(tools=[...]) 的 tools 參數。
        """
        properties: Dict[str, Any] = {}
        for p in self.parameters:
            prop: Dict[str, Any] = {
                "type": p.type,
                "description": p.description,
            }
            if p.enum:
                prop["enum"] = p.enum
            if p.default is not None:
                prop["default"] = p.default
            properties[p.name] = prop

        required = [p.name for p in self.parameters if p.required]

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

    def __repr__(self) -> str:
        return f"<Tool name={self.name!r}>"


# ─────────────────────────────────────────────────────────────
# ToolRegistry — 全域工具管理器
# ─────────────────────────────────────────────────────────────

class ToolRegistry:
    """
    全域工具註冊表。

    範例：
        registry = ToolRegistry()
        registry.register(KBSearchTool(kb_retriever))
        functions = registry.list_openai_functions()   # 傳給 LLM
        result = await registry.call("kb_search", query="REST API")
    """

    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """註冊一個工具（覆蓋同名舊工具）。"""
        self._tools[tool.name] = tool
        logger.debug(f"[ToolRegistry] 已註冊工具：{tool.name}")

    def unregister(self, name: str) -> None:
        """移除已註冊的工具。"""
        self._tools.pop(name, None)

    def get(self, name: str) -> Optional[Tool]:
        """依名稱取得工具，不存在回傳 None。"""
        return self._tools.get(name)

    def names(self) -> List[str]:
        """回傳所有已註冊工具名稱。"""
        return list(self._tools.keys())

    def list_openai_functions(self) -> List[Dict[str, Any]]:
        """
        回傳所有工具的 OpenAI Function Calling 描述清單。
        可直接傳入 openai.chat.completions.create(tools=...) 的 tools 參數。
        """
        return [t.to_openai_function() for t in self._tools.values()]

    async def call(self, name: str, **kwargs) -> ToolResult:
        """
        呼叫指定工具執行，回傳 ToolResult。

        若工具不存在，回傳 success=False 的 ToolResult。
        """
        tool = self._tools.get(name)
        if not tool:
            return ToolResult(
                success=False,
                error=f"工具 '{name}' 不存在（已註冊：{', '.join(self._tools)}）",
            )
        try:
            result = await tool.execute(**kwargs)
            return result
        except TypeError as exc:
            return ToolResult(success=False, error=f"參數錯誤：{exc}")
        except Exception as exc:
            logger.error(f"[ToolRegistry] 工具執行失敗 {name}: {exc}")
            return ToolResult(success=False, error=str(exc))

    def __len__(self) -> int:
        return len(self._tools)

    def __repr__(self) -> str:
        return f"<ToolRegistry tools={self.names()}>"


# ─────────────────────────────────────────────────────────────
# 內建工具：KBSearchTool
# ─────────────────────────────────────────────────────────────

class KBSearchTool(Tool):
    """
    知識庫語意搜尋工具。

    LLM 需要從企業文件中查找特定資訊時自動呼叫。
    傳入 tenant_id 進行搜尋，回傳最相關的文件段落。
    """

    name = "kb_search"
    description = (
        "在企業私有知識庫中搜尋最相關的文件段落。"
        "當需要查找企業政策、合約條款、技術文件或任何內部資料時使用。"
    )
    parameters = [
        ToolParam(
            name="query",
            type="string",
            description="搜尋查詢字串（可使用自然語言）",
        ),
        ToolParam(
            name="top_k",
            type="integer",
            description="回傳結果數量（預設 5，最多 20）",
            required=False,
            default=5,
        ),
    ]

    def __init__(self, tenant_id: UUID, kb_retriever=None) -> None:
        self.tenant_id = tenant_id
        self._retriever = kb_retriever

    async def execute(self, query: str, top_k: int = 5, **kwargs) -> ToolResult:
        import asyncio

        if not self._retriever:
            from app.services.kb_retrieval import KnowledgeBaseRetriever
            self._retriever = KnowledgeBaseRetriever()

        top_k = min(max(1, int(top_k)), 20)

        try:
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                None,
                lambda: self._retriever.search(
                    tenant_id=self.tenant_id,
                    query=query,
                    top_k=top_k,
                ),
            )
            return ToolResult(
                success=True,
                data={
                    "results": [
                        {
                            "content": r.get("content", "")[:800],
                            "filename": r.get("filename", ""),
                            "score": r.get("score", 0),
                        }
                        for r in results
                    ],
                    "total": len(results),
                    "query": query,
                },
                metadata={"tool": "kb_search", "top_k": top_k},
            )
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))


# ─────────────────────────────────────────────────────────────
# 內建工具：DocumentListTool
# ─────────────────────────────────────────────────────────────

class DocumentListTool(Tool):
    """
    列舉知識庫中符合條件的文件。

    LLM 需要知道「有哪些文件」或找特定類型文件清單時使用。
    """

    name = "document_list"
    description = (
        "列出企業知識庫中的文件清單，可依類型或狀態篩選。"
        "當需要了解「知識庫中有哪些文件」或「有沒有 XXX 類型的文件」時使用。"
    )
    parameters = [
        ToolParam(
            name="file_type",
            type="string",
            description="文件類型篩選（pdf / docx / xlsx / txt，留空則全部）",
            required=False,
            default=None,
        ),
        ToolParam(
            name="limit",
            type="integer",
            description="最多回傳筆數（預設 20）",
            required=False,
            default=20,
        ),
    ]

    def __init__(self, tenant_id: UUID) -> None:
        self.tenant_id = tenant_id

    async def execute(
        self,
        file_type: Optional[str] = None,
        limit: int = 20,
        **kwargs,
    ) -> ToolResult:
        from app.db.session import SessionLocal
        from app.models.document import Document

        limit = min(max(1, int(limit)), 100)
        db = SessionLocal()
        try:
            query = db.query(Document).filter(
                Document.tenant_id == self.tenant_id,
                Document.status == "completed",
            )
            if file_type:
                query = query.filter(Document.file_type == file_type.lower())
            docs = query.order_by(Document.created_at.desc()).limit(limit).all()
            return ToolResult(
                success=True,
                data={
                    "documents": [
                        {
                            "id": str(d.id),
                            "filename": d.filename,
                            "file_type": d.file_type,
                            "chunk_count": d.chunk_count,
                            "created_at": d.created_at.isoformat() if d.created_at else None,
                        }
                        for d in docs
                    ],
                    "total": len(docs),
                },
                metadata={"tool": "document_list"},
            )
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))
        finally:
            db.close()


# ─────────────────────────────────────────────────────────────
# 全局單例 & 工廠函數
# ─────────────────────────────────────────────────────────────

# 全局 Registry（應用層共用）
_global_registry: Optional[ToolRegistry] = None


def get_registry() -> ToolRegistry:
    """取得全局工具 Registry（單例）。"""
    global _global_registry
    if _global_registry is None:
        _global_registry = ToolRegistry()
    return _global_registry


def build_tenant_registry(tenant_id: UUID, kb_retriever=None) -> ToolRegistry:
    """
    為指定租戶建立工具 Registry，並預先載入內建工具。

    應在處理每個 chat request 前呼叫，避免不同租戶資料交叉。
    """
    registry = ToolRegistry()
    registry.register(KBSearchTool(tenant_id=tenant_id, kb_retriever=kb_retriever))
    registry.register(DocumentListTool(tenant_id=tenant_id))
    return registry
