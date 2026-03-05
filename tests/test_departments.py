"""
Departments Tests — /api/v1/departments
測試部門 CRUD、樹狀結構、功能權限管理
"""
import pytest
from httpx import AsyncClient
from tests.conftest import create_tenant, create_user, login_user


async def _owner_setup(client, superuser_headers, suffix):
    t = await create_tenant(client, superuser_headers, {"name": f"DeptCo {suffix}"})
    await create_user(client, superuser_headers, {
        "email": f"owner@dept{suffix}.com", "password": "Owner123!",
        "full_name": "Owner", "role": "owner", "tenant_id": t["id"],
    })
    h = await login_user(client, f"owner@dept{suffix}.com", "Owner123!")
    return t, h


@pytest.mark.asyncio
async def test_create_department(client: AsyncClient, superuser_headers: dict):
    """admin 可以建立部門"""
    t, h = await _owner_setup(client, superuser_headers, "cr")

    resp = await client.post("/api/v1/departments/", headers=h, json={
        "name": "工程部", "description": "負責系統開發",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "工程部"
    assert "id" in data


@pytest.mark.asyncio
async def test_list_departments(client: AsyncClient, superuser_headers: dict):
    """可以列出部門列表"""
    t, h = await _owner_setup(client, superuser_headers, "ls")

    await client.post("/api/v1/departments/", headers=h, json={"name": "業務部"})
    await client.post("/api/v1/departments/", headers=h, json={"name": "人資部"})

    resp = await client.get("/api/v1/departments/", headers=h)
    assert resp.status_code == 200
    names = [d["name"] for d in resp.json()]
    assert "業務部" in names
    assert "人資部" in names


@pytest.mark.asyncio
async def test_department_tree(client: AsyncClient, superuser_headers: dict):
    """可以取得部門樹狀結構"""
    _, h = await _owner_setup(client, superuser_headers, "tr")

    resp = await client.get("/api/v1/departments/tree", headers=h)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_update_department(client: AsyncClient, superuser_headers: dict):
    """可以更新部門資訊"""
    _, h = await _owner_setup(client, superuser_headers, "up")

    create_resp = await client.post("/api/v1/departments/", headers=h, json={"name": "舊名稱"})
    dept_id = create_resp.json()["id"]

    update_resp = await client.put(f"/api/v1/departments/{dept_id}", headers=h, json={
        "name": "新名稱", "description": "已更新",
    })
    assert update_resp.status_code == 200
    assert update_resp.json()["name"] == "新名稱"


@pytest.mark.asyncio
async def test_delete_department(client: AsyncClient, superuser_headers: dict):
    """可以刪除空部門"""
    _, h = await _owner_setup(client, superuser_headers, "de")

    create_resp = await client.post("/api/v1/departments/", headers=h, json={"name": "待刪部門"})
    dept_id = create_resp.json()["id"]

    del_resp = await client.delete(f"/api/v1/departments/{dept_id}", headers=h)
    assert del_resp.status_code in [200, 204]

    # Either 404 (hard-delete) or removed from list (soft-delete / list filter)
    list_resp = await client.get("/api/v1/departments/", headers=h)
    if list_resp.status_code == 200:
        ids_in_list = [d["id"] for d in list_resp.json()]
        assert dept_id not in ids_in_list, "Deleted department still appears in list"


@pytest.mark.asyncio
async def test_employee_cannot_create_department(client: AsyncClient, superuser_headers: dict):
    """employee 無法建立部門"""
    t, _ = await _owner_setup(client, superuser_headers, "ep")
    await create_user(client, superuser_headers, {
        "email": "emp@deptep.com", "password": "Emp123!",
        "full_name": "Emp", "role": "employee", "tenant_id": t["id"],
    })
    h_emp = await login_user(client, "emp@deptep.com", "Emp123!")

    resp = await client.post("/api/v1/departments/", headers=h_emp, json={"name": "非法部門"})
    assert resp.status_code in [401, 403]
