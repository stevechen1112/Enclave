"""Phase 6 — MCP tool discovery for Agent runtime."""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class MCPToolDiscovery:
    """Discover tools from configured MCP servers (read-only discovery)."""

    def __init__(self, servers: List[Dict[str, str]] = None):
        self.servers = servers or []

    def discover(self) -> List[Dict[str, Any]]:
        tools: List[Dict[str, Any]] = []
        for server in self.servers:
            name = server.get("name", "mcp")
            tools.append({
                "name": f"mcp_{name}_search",
                "description": f"MCP tool from {name}",
                "risk": "read_only",
                "category": "external_system",
                "server": name,
                "requires_approval": False,
            })
        return tools

    def to_openai_functions(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            }
            for t in self.discover()
        ]
