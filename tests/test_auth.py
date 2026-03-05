"""
Authentication Tests — /api/v1/auth
測試 JWT 登入、token 格式、無效憑證拒絕
"""
import pytest
from httpx import AsyncClient
from tests.conftest import create_tenant, create_user, login_user


# ── 登入成功 ──

@pytest.mark.asyncio
async def test_superuser_login_returns_token(client: AsyncClient, superuser_headers: dict):
    """superuser 登入應回傳有效 JWT"""
    resp = await client.post(
        "/api/v1/auth/login/access-token",
        data={"username": "superuser@test.com", "password": "Super123!"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert len(data["access_token"]) > 20


@pytest.mark.asyncio
async def test_tenant_user_login(client: AsyncClient, superuser_headers: dict):
    """租戶使用者登入應成功"""
    t = await create_tenant(client, superuser_headers, {"name": "Auth Co"})
    await create_user(client, superuser_headers, {
        "email": "auth@authco.com", "password": "AuthPass1!",
        "full_name": "Auth User", "role": "employee", "tenant_id": t["id"],
    })
    resp = await client.post(
        "/api/v1/auth/login/access-token",
        data={"username": "auth@authco.com", "password": "AuthPass1!"},
    )
    assert resp.status_code == 200
    assert "access_token" in resp.json()


# ── 登入失敗 ──

@pytest.mark.asyncio
async def test_wrong_password_rejected(client: AsyncClient):
    """密碼錯誤應回傳 400 或 401"""
    resp = await client.post(
        "/api/v1/auth/login/access-token",
        data={"username": "superuser@test.com", "password": "WrongPass!"},
    )
    assert resp.status_code in [400, 401]


@pytest.mark.asyncio
async def test_nonexistent_user_rejected(client: AsyncClient):
    """不存在的帳號應回傳 400 或 401"""
    resp = await client.post(
        "/api/v1/auth/login/access-token",
        data={"username": "nobody@nowhere.com", "password": "Any123!"},
    )
    assert resp.status_code in [400, 401]


# ── Token 驗證 ──

@pytest.mark.asyncio
async def test_invalid_token_rejected(client: AsyncClient):
    """偽造 token 呼叫受保護端點應回傳 401 或 403"""
    resp = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": "Bearer this.is.fake"},
    )
    assert resp.status_code in [401, 403]


@pytest.mark.asyncio
async def test_missing_token_rejected(client: AsyncClient):
    """無 token 呼叫受保護端點應回傳 401"""
    resp = await client.get("/api/v1/users/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_valid_token_grants_access(client: AsyncClient, superuser_headers: dict):
    """有效 token 應能存取 /users/me"""
    resp = await client.get("/api/v1/users/me", headers=superuser_headers)
    assert resp.status_code == 200
    assert resp.json()["email"] == "superuser@test.com"
