"""
Users Tests — /api/v1/users
測試使用者建立、查詢自身資料、角色限制
"""
import pytest
from httpx import AsyncClient
from tests.conftest import create_tenant, create_user, login_user


@pytest.mark.asyncio
async def test_get_me_returns_own_profile(client: AsyncClient, superuser_headers: dict):
    """GET /users/me 應回傳自己的資料"""
    resp = await client.get("/api/v1/users/me", headers=superuser_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "superuser@test.com"
    assert data["is_superuser"] is True


@pytest.mark.asyncio
async def test_admin_can_create_user(client: AsyncClient, superuser_headers: dict):
    """admin 可以建立使用者"""
    t = await create_tenant(client, superuser_headers, {"name": "User Co"})
    await create_user(client, superuser_headers, {
        "email": "admin@userco.com", "password": "Admin123!",
        "full_name": "Admin", "role": "admin", "tenant_id": t["id"],
    })
    h = await login_user(client, "admin@userco.com", "Admin123!")

    resp = await client.post("/api/v1/users/", headers=h, json={
        "email": "newuser@userco.com", "password": "New123!",
        "full_name": "New User", "role": "employee", "tenant_id": t["id"],
    })
    assert resp.status_code == 200
    assert resp.json()["email"] == "newuser@userco.com"
    assert resp.json()["role"] == "employee"


@pytest.mark.asyncio
async def test_duplicate_email_rejected(client: AsyncClient, superuser_headers: dict):
    """重複 email 應回傳 400"""
    t = await create_tenant(client, superuser_headers, {"name": "Dup Co"})
    await create_user(client, superuser_headers, {
        "email": "dup@dupco.com", "password": "Dup123!",
        "full_name": "Dup", "role": "employee", "tenant_id": t["id"],
    })
    # 再建立一次同 email
    resp = await client.post("/api/v1/users/", headers=superuser_headers, json={
        "email": "dup@dupco.com", "password": "Another1!",
        "full_name": "Dup2", "role": "employee", "tenant_id": t["id"],
    })
    assert resp.status_code in [400, 409]


@pytest.mark.asyncio
async def test_employee_cannot_create_user(client: AsyncClient, superuser_headers: dict):
    """employee 無權建立使用者"""
    t = await create_tenant(client, superuser_headers, {"name": "EmpCo"})
    await create_user(client, superuser_headers, {
        "email": "emp@empco.com", "password": "Emp123!",
        "full_name": "Emp", "role": "employee", "tenant_id": t["id"],
    })
    h = await login_user(client, "emp@empco.com", "Emp123!")

    resp = await client.post("/api/v1/users/", headers=h, json={
        "email": "victim@empco.com", "password": "V123!",
        "full_name": "Victim", "role": "employee", "tenant_id": t["id"],
    })
    assert resp.status_code in [401, 403]


@pytest.mark.asyncio
async def test_get_me_reflects_role(client: AsyncClient, superuser_headers: dict):
    """GET /users/me 回傳正確角色"""
    t = await create_tenant(client, superuser_headers, {"name": "RoleCo"})
    await create_user(client, superuser_headers, {
        "email": "hr@roleco.com", "password": "HR123!",
        "full_name": "HR", "role": "hr", "tenant_id": t["id"],
    })
    h = await login_user(client, "hr@roleco.com", "HR123!")
    resp = await client.get("/api/v1/users/me", headers=h)
    assert resp.status_code == 200
    assert resp.json()["role"] == "hr"
