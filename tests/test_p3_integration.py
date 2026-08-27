"""
P3：需求驅動整合 — 單元測試。

涵蓋：
- P3-1 Connector Materialize
- P3-2 Read-only FastMCP Server
- P3-3 MCP Client + Allowlist + ApprovalGate
- P3-4 Docling Parser Ablation
"""
import pytest
from unittest.mock import MagicMock, patch

from app.services.connector_materialize import ResourceDownloader
from app.services.mcp_server import ReadOnlyFastMCPServer
from app.services.mcp_client import MCPClient, MCPServerConfig
from app.services.docling_ablation import (
    DoclingParser,
    ParserAblationRunner,
    AblationComparison,
    ParseResult,
)


# ── P3-1 Connector Materialize ──

class TestResourceDownloader:
    def test_local_file_exists(self, tmp_path):
        f = tmp_path / "test.pdf"
        f.write_text("content")
        dl = ResourceDownloader(upload_dir=str(tmp_path), max_size_mb=10)
        result = dl.resolve_and_download(
            {"file_path": str(f), "id": "res1"},
            tenant_id="tenant1",
        )
        assert result == str(f)

    def test_local_file_not_found(self, tmp_path):
        dl = ResourceDownloader(upload_dir=str(tmp_path), max_size_mb=10)
        result = dl.resolve_and_download(
            {"file_path": str(tmp_path / "nonexistent.pdf")},
            tenant_id="tenant1",
        )
        assert result is None

    def test_no_path(self, tmp_path):
        dl = ResourceDownloader(upload_dir=str(tmp_path), max_size_mb=10)
        result = dl.resolve_and_download({"id": "res1"}, tenant_id="tenant1")
        assert result is None

    def test_is_remote_uri(self, tmp_path):
        dl = ResourceDownloader(upload_dir=str(tmp_path))
        assert dl._is_remote_uri("https://example.com/file.pdf")
        assert dl._is_remote_uri("s3://bucket/key.pdf")
        assert dl._is_remote_uri("http://localhost:8080/file.pdf")
        assert not dl._is_remote_uri("/local/path/file.pdf")
        assert not dl._is_remote_uri("C:\\Users\\file.pdf")

    def test_sanitize_filename(self, tmp_path):
        dl = ResourceDownloader(upload_dir=str(tmp_path))
        assert dl._sanitize_filename("../../../etc/passwd") == "passwd"
        assert dl._sanitize_filename("normal.pdf") == "normal.pdf"
        # 長檔名截斷
        long_name = "a" * 250 + ".pdf"
        sanitized = dl._sanitize_filename(long_name)
        assert len(sanitized) <= 200

    def test_download_path_traversal_prevention(self, tmp_path):
        """確保下載路徑不會被路徑穿越攻擊。"""
        dl = ResourceDownloader(upload_dir=str(tmp_path), max_size_mb=10)
        # 嘗試路徑穿越
        result = dl.resolve_and_download(
            {"file_path": "../../../etc/passwd", "id": "res1"},
            tenant_id="tenant1",
        )
        # 本機路徑穿越應被 _sanitize_filename 阻擋（或檔案不存在）
        assert result is None or "/etc/passwd" not in str(result)

    @pytest.mark.parametrize(
        "unsafe_path",
        ("../secret.txt", "safe/../../secret.txt", r"..\..\secret.txt"),
    )
    def test_rejects_parent_traversal_before_touching_filesystem(
        self, tmp_path, unsafe_path
    ):
        dl = ResourceDownloader(upload_dir=str(tmp_path), max_size_mb=10)
        assert (
            dl.resolve_and_download(
                {"file_path": unsafe_path, "id": "untrusted-resource"},
                tenant_id="tenant1",
            )
            is None
        )


# ── P3-2 Read-only FastMCP Server ──

class TestFastMCPServer:
    def test_list_tools(self):
        server = ReadOnlyFastMCPServer()
        tools = server.list_tools()
        names = [t.name for t in tools]
        assert "search" in names
        assert "chat" in names
        assert "catalog" in names
        assert "health" in names

    def test_all_tools_read_only(self):
        server = ReadOnlyFastMCPServer()
        for tool in server.list_tools():
            assert tool.read_only is True, f"Tool {tool.name} should be read-only"

    def test_call_tool_requires_authz(self):
        server = ReadOnlyFastMCPServer()
        result = server.call_tool("search", {"query": "test"}, authz=None)
        assert result.is_error is True
        assert "AuthorizationContext" in result.error

    def test_call_unknown_tool(self):
        server = ReadOnlyFastMCPServer()
        authz = MagicMock()
        result = server.call_tool("unknown_tool", {}, authz=authz)
        assert result.is_error is True
        assert "Unknown tool" in result.error

    def test_health_check(self):
        server = ReadOnlyFastMCPServer()
        authz = MagicMock()
        result = server.call_tool("health", {}, authz=authz)
        assert result.is_error is False
        assert "ok" in result.content

    def test_search_empty_query(self):
        server = ReadOnlyFastMCPServer()
        authz = MagicMock()
        result = server.call_tool("search", {"query": ""}, authz=authz)
        assert result.is_error is True
        assert "query is required" in result.error

    def test_openapi_schema(self):
        server = ReadOnlyFastMCPServer()
        schema = server.to_openapi_schema()
        assert schema["info"]["title"] == "Enclave Read-only MCP Server"
        assert "paths" in schema


# ── P3-3 MCP Client ──

class TestMCPClient:
    def test_add_and_list_server(self):
        client = MCPClient()
        client.add_server(MCPServerConfig(name="test", url="http://localhost:9000"))
        assert "test" in client.list_servers()

    def test_remove_server(self):
        client = MCPClient()
        client.add_server(MCPServerConfig(name="test", url="http://localhost:9000"))
        client.remove_server("test")
        assert "test" not in client.list_servers()

    def test_is_allowed_server_disabled(self):
        """MCP_CLIENT_ENABLED=false 時不允許任何 server。"""
        client = MCPClient()
        client.add_server(MCPServerConfig(name="test", url="http://localhost:9000"))
        with patch("app.config.settings") as mock_settings:
            mock_settings.MCP_CLIENT_ENABLED = False
            assert not client.is_allowed_server("test")

    def test_is_tool_allowed(self):
        client = MCPClient()
        client.add_server(MCPServerConfig(
            name="test",
            url="http://localhost:9000",
            allowed_tools=["search", "chat"],
            blocked_tools=["delete"],
        ))
        assert client.is_tool_allowed("test", "search")
        assert client.is_tool_allowed("test", "chat")
        assert not client.is_tool_allowed("test", "delete")
        assert not client.is_tool_allowed("test", "upload")
        assert not client.is_tool_allowed("unknown", "search")

    def test_is_mutating_tool(self):
        client = MCPClient()
        assert client._is_mutating_tool("server", "create_document")
        assert client._is_mutating_tool("server", "update_record")
        assert client._is_mutating_tool("server", "delete_file")
        assert not client._is_mutating_tool("server", "search")
        assert not client._is_mutating_tool("server", "chat")
        assert not client._is_mutating_tool("server", "catalog")
        # word boundary — address 不應被判為 mutating
        assert not client._is_mutating_tool("server", "address_lookup")
        assert not client._is_mutating_tool("server", "settings_get")

    def test_call_tool_requires_authz(self):
        client = MCPClient()
        with pytest.raises(ValueError, match="AuthorizationContext"):
            client.call_tool("server", "tool", {}, authz=None)

    def test_call_tool_not_enabled(self):
        client = MCPClient()
        authz = MagicMock()
        with patch("app.config.settings") as mock_settings:
            mock_settings.MCP_CLIENT_ENABLED = False
            with pytest.raises(RuntimeError, match="MCP_CLIENT_ENABLED"):
                client.call_tool("test", "search", {}, authz=authz)

    def test_call_tool_server_not_in_allowlist(self):
        client = MCPClient()
        authz = MagicMock()
        with patch("app.config.settings") as mock_settings:
            mock_settings.MCP_CLIENT_ENABLED = True
            mock_settings.MCP_CLIENT_ALLOWLIST = ""
            with pytest.raises(ValueError, match="not in allowlist"):
                client.call_tool("unknown", "search", {}, authz=authz)


# ── P3-4 Docling Ablation ──

class TestDoclingAblation:
    def test_parse_result_success(self):
        result = ParseResult(text="content", provider="docling")
        assert result.success is True

    def test_parse_result_error(self):
        result = ParseResult(error="failed")
        assert result.success is False

    def test_ablation_comparison_winner(self):
        comparison = AblationComparison(file_path="test.pdf", file_type="pdf")
        comparison.results["native"] = ParseResult(text="short", provider="native", elapsed_seconds=1.0)
        comparison.results["docling"] = ParseResult(
            text="much longer text with more content",
            tables=[{"rows": 2}],
            provider="docling",
            elapsed_seconds=2.0,
        )
        winner, reason = comparison.get_winner()
        assert winner in ("native", "docling")
        assert "score=" in reason

    def test_ablation_comparison_no_results(self):
        comparison = AblationComparison()
        winner, reason = comparison.get_winner()
        assert winner == ""
        assert reason == "no results"

    def test_ablation_to_dict(self):
        comparison = AblationComparison(file_path="test.pdf", file_type="pdf")
        comparison.results["native"] = ParseResult(text="content", provider="native")
        d = comparison.to_dict()
        assert d["file_path"] == "test.pdf"
        assert "native" in d["results"]
        assert "winner" in d

    def test_docling_not_available_when_disabled(self):
        parser = DoclingParser()
        with patch("app.config.settings") as mock_settings:
            mock_settings.DOCLING_ENABLED = False
            assert parser.is_available() is False

    def test_ablation_runner_native_only(self, tmp_path):
        """只跑 native parser（Docling 不可用時）。"""
        f = tmp_path / "test.txt"
        f.write_text("test content")
        runner = ParserAblationRunner()
        with patch.object(runner.docling, "is_available", return_value=False):
            comparison = runner.run_ablation(str(f), "txt", include_native=True, include_docling=True)
            assert "native" in comparison.results
            assert "docling" not in comparison.results
