"""
P3-2：MCP Server API endpoint — 暴露 read-only FastMCP server。

GET  /api/v1/mcp/tools — 列出工具
POST /api/v1/mcp/tools/{name} — 執行工具
GET  /api/v1/mcp/openapi.json — OpenAPI schema
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from app.api import deps
from app.models.user import User

router = APIRouter()


@router.get("/mcp/tools")
async def list_mcp_tools(
    current_user: User = Depends(deps.get_current_verified_user),
):
    """列出所有 read-only MCP 工具。"""
    from app.config import settings
    if not settings.MCP_SERVER_ENABLED:
        raise HTTPException(status_code=404, detail="MCP server not enabled")

    from app.services.mcp_server import get_mcp_server
    server = get_mcp_server()
    tools = server.list_tools()
    return {
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
                "read_only": t.read_only,
            }
            for t in tools
        ]
    }


@router.post("/mcp/tools/{tool_name}")
async def call_mcp_tool(
    tool_name: str,
    request: Request,
    current_user: User = Depends(deps.get_current_verified_user),
):
    """執行 read-only MCP 工具。"""
    from app.config import settings
    if not settings.MCP_SERVER_ENABLED:
        raise HTTPException(status_code=404, detail="MCP server not enabled")

    from app.core.authorization import AuthorizationContext
    from app.services.mcp_server import get_mcp_server

    body = await request.json()
    arguments = body.get("arguments", {})
    authz = AuthorizationContext.from_user(current_user)

    server = get_mcp_server()
    result = server.call_tool(tool_name, arguments, authz)

    if result.is_error:
        raise HTTPException(status_code=400, detail=result.error)

    return {"content": result.content}


@router.get("/mcp/openapi.json")
async def mcp_openapi_schema(
    current_user: User = Depends(deps.get_current_verified_user),
):
    """MCP OpenAPI schema。"""
    from app.config import settings
    if not settings.MCP_SERVER_ENABLED:
        raise HTTPException(status_code=404, detail="MCP server not enabled")

    from app.services.mcp_server import get_mcp_server
    server = get_mcp_server()
    return server.to_openapi_schema()