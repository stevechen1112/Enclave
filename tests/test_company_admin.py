"""
Phase 3 Integration Tests — Tenant Self-Service (T3-2)
"""
import pytest
from httpx import AsyncClient
from tests.conftest import create_tenant, create_user, login_user

CHAT_URL = "/api/v1/chat/chat"


async def _setup(client, superuser_headers, tax_id):
    tid = tax_id.lower()  # EmailStr normalizes domain to lowercase
    t = await create_tenant(client, superuser_headers, {
        "name": f"Co {tax_id}", "tax_id": tax_id,
        "contact_name": "C", "contact_email": f"c@{tid}.com",
        "contact_phone": f"09{tax_id}",
    })
    await create_user(client, superuser_headers, {
        "email": f"owner@{tid}.com", "password": "Owner123!",
        "full_name": f"Owner", "role": "owner",
        "tenant_id": t["id"],
    })
    h = await login_user(client, f"owner@{tid}.com", "Owner123!")
    return t, h


@pytest.mark.asyncio
async def test_company_dashboard(client: AsyncClient, superuser_headers: dict):
    """測試公司儀表板"""
    t, h = await _setup(client, superuser_headers, "CD01")

    r = await client.get("/api/v1/company/dashboard", headers=h)
    assert r.status_code == 200
    data = r.json()
    assert data["company_name"] == "Co CD01"
    assert "quota_status" in data
    assert data["user_count"] >= 1


@pytest.mark.asyncio
async def test_company_profile(client: AsyncClient, superuser_headers: dict):
    """測試公司資訊查看"""
    t, h = await _setup(client, superuser_headers, "CP01")

    r = await client.get("/api/v1/company/profile", headers=h)
    assert r.status_code == 200
    assert r.json()["name"] == "Co CP01"


@pytest.mark.asyncio
async def test_company_quota_view(client: AsyncClient, superuser_headers: dict):
    """測試公司配額查看"""
    t, h = await _setup(client, superuser_headers, "CQ01")

    r = await client.get("/api/v1/company/quota", headers=h)
    assert r.status_code == 200
    data = r.json()
    assert "max_users" in data
    assert "is_over_quota" in data


@pytest.mark.asyncio
async def test_invite_and_list_users(client: AsyncClient, superuser_headers: dict):
    """測試邀請使用者並列出"""
    t, h = await _setup(client, superuser_headers, "IU01")

    # 邀請新員工
    r = await client.post("/api/v1/company/users/invite", headers=h, json={
        "email": "emp@iu01.com",
        "full_name": "Employee One",
        "role": "employee",
        "password": "Emp12345!",
    })
    assert r.status_code == 200
    assert r.json()["email"] == "emp@iu01.com"
    assert r.json()["role"] == "employee"

    # 列出使用者
    r2 = await client.get("/api/v1/company/users", headers=h)
    assert r2.status_code == 200
    emails = {u["email"] for u in r2.json()}
    assert "emp@iu01.com" in emails
    assert f"owner@iu01.com" in emails


@pytest.mark.asyncio
async def test_update_user_role(client: AsyncClient, superuser_headers: dict):
    """測試更新使用者角色"""
    t, h = await _setup(client, superuser_headers, "UR01")

    invite_r = await client.post("/api/v1/company/users/invite", headers=h, json={
        "email": "emp@ur01.com", "full_name": "Emp",
        "role": "employee", "password": "Emp12345!",
    })
    user_id = invite_r.json()["id"]

    # 升級為 HR
    r = await client.put(f"/api/v1/company/users/{user_id}", headers=h, json={
        "role": "hr",
    })
    assert r.status_code == 200
    assert r.json()["role"] == "hr"


@pytest.mark.asyncio
async def test_deactivate_user(client: AsyncClient, superuser_headers: dict):
    """測試停用使用者"""
    t, h = await _setup(client, superuser_headers, "DU01")

    invite_r = await client.post("/api/v1/company/users/invite", headers=h, json={
        "email": "emp@du01.com", "full_name": "Emp",
        "role": "employee", "password": "Emp12345!",
    })
    user_id = invite_r.json()["id"]

    r = await client.delete(f"/api/v1/company/users/{user_id}", headers=h)
    assert r.status_code == 200
    assert "停用" in r.json()["message"]


@pytest.mark.asyncio
async def test_employee_cannot_access_company_admin(client: AsyncClient, superuser_headers: dict):
    """測試員工無法存取公司管理功能"""
    t, h_owner = await _setup(client, superuser_headers, "EC01")

    await create_user(client, superuser_headers, {
        "email": "emp@ec01.com", "password": "Emp12345!",
        "full_name": "Emp", "role": "employee",
        "tenant_id": t["id"],
    })
    h_emp = await login_user(client, "emp@ec01.com", "Emp12345!")

    assert (await client.get("/api/v1/company/dashboard", headers=h_emp)).status_code == 403
    assert (await client.get("/api/v1/company/users", headers=h_emp)).status_code == 403


@pytest.mark.asyncio
async def test_company_usage_summary(client: AsyncClient, superuser_headers: dict):
    """測試公司用量摘要"""
    t, h = await _setup(client, superuser_headers, "US01")

    await client.post(CHAT_URL, headers=h, json={"question": "test"})

    r = await client.get("/api/v1/company/usage/summary", headers=h)
    assert r.status_code == 200
    data = r.json()
    assert data["total_actions"] >= 1


@pytest.mark.asyncio
async def test_company_usage_by_user(client: AsyncClient, superuser_headers: dict):
    """測試每位使用者用量"""
    t, h = await _setup(client, superuser_headers, "UU01")

    await client.post(CHAT_URL, headers=h, json={"question": "owner q"})

    r = await client.get("/api/v1/company/usage/by-user", headers=h)
    assert r.status_code == 200
    data = r.json()
    assert len(data) >= 1
    assert any(u["email"] == "owner@uu01.com" for u in data)
