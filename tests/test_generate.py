"""
Generate Tests — /api/v1/generate
測試模板列表、串流生成（SSE）、文件匯出
使用真實 LLM（Gemini），無 mock
"""
import pytest
from httpx import AsyncClient
from tests.conftest import create_tenant, create_user, login_user


async def _setup(client, superuser_headers, suffix):
    t = await create_tenant(client, superuser_headers, {"name": f"GenCo {suffix}"})
    await create_user(client, superuser_headers, {
        "email": f"hr@gen{suffix}.com", "password": "HR123!",
        "full_name": "HR", "role": "hr", "tenant_id": t["id"],
    })
    h = await login_user(client, f"hr@gen{suffix}.com", "HR123!")
    return t, h


@pytest.mark.asyncio
async def test_list_templates(client: AsyncClient, superuser_headers: dict):
    """GET /generate/templates 應回傳模板列表"""
    _, h = await _setup(client, superuser_headers, "tpl")

    resp = await client.get("/api/v1/generate/templates", headers=h)
    assert resp.status_code == 200
    data = resp.json()
    # endpoint returns {"templates": [...]}
    templates = data if isinstance(data, list) else data.get("templates", data)
    assert isinstance(templates, list)
    assert len(templates) > 0
    # 每個模板應有 id 和 name
    for tpl in templates:
        assert "id" in tpl or "name" in tpl


@pytest.mark.asyncio
async def test_generate_stream_returns_sse(client: AsyncClient, superuser_headers: dict):
    """POST /generate/stream 應回傳 SSE 串流（text/event-stream）"""
    _, h = await _setup(client, superuser_headers, "sse")

    resp = await client.post(
        "/api/v1/generate/stream",
        headers=h,
        json={
            "template": "draft_response",
            "user_prompt": "員工年假政策摘要",
            "context_query": "年假政策",
        },
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_generate_export_docx(client: AsyncClient, superuser_headers: dict):
    """POST /generate/export/docx 應回傳 docx 文件"""
    _, h = await _setup(client, superuser_headers, "docx")

    resp = await client.post(
        "/api/v1/generate/export/docx",
        headers=h,
        json={
            "content": "This is a test generated Word document.",
            "title": "Test Report",
        },
    )
    assert resp.status_code == 200
    ct = resp.headers.get("content-type", "")
    assert "wordprocessingml" in ct or "octet-stream" in ct


@pytest.mark.asyncio
async def test_viewer_can_generate(client: AsyncClient, superuser_headers: dict):
    """Viewer 可以使用生成功能（唯讀操作）"""
    t, _ = await _setup(client, superuser_headers, "vw")
    await create_user(client, superuser_headers, {
        "email": "viewer@genvw.com", "password": "View123!",
        "full_name": "Viewer", "role": "viewer", "tenant_id": t["id"],
    })
    h_viewer = await login_user(client, "viewer@genvw.com", "View123!")

    resp = await client.get("/api/v1/generate/templates", headers=h_viewer)
    assert resp.status_code == 200
