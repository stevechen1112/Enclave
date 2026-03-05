"""
Enclave Agent — 主動索引引擎

Phase 10 核心模組，負責監控本機資料夾、工具調用框架與排程批次處理。

模組說明：
  file_watcher.py   — 使用 watchdog 監控指定資料夾的新增/修改/刪除事件
  scheduler.py      — 排程批次重建索引（APScheduler 每日執行）
  tool_registry.py  — LLM 工具調用框架（Tool ABC、ToolRegistry、內建工具）
  classifier.py     — AI 文件分類提案引擎（未來擴充）
  review_queue.py   — 人工審核佇列狀態機（未來擴充）
"""

from app.agent.tool_registry import (
    Tool,
    ToolParam,
    ToolResult,
    ToolRegistry,
    KBSearchTool,
    DocumentListTool,
    get_registry,
    build_tenant_registry,
)

__all__ = [
    "Tool",
    "ToolParam",
    "ToolResult",
    "ToolRegistry",
    "KBSearchTool",
    "DocumentListTool",
    "get_registry",
    "build_tenant_registry",
]
