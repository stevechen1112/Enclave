"""
Permission & Role-Based Access Control Tests
測試不同角色的權限控制
"""
import pytest
from httpx import AsyncClient
from tests.conftest import create_tenant, create_user, login_user

CHAT_URL = "/api/v1/chat/chat"


@pytest.mark.asyncio
async def test_employee_cannot_delete_documents(client: AsyncClient, superuser_headers: dict):
    """測試一般員工無法刪除文件"""

    td = await create_tenant(client, superuser_headers, {
        "name": "Perm Test Co", "tax_id": "10203040",
        "contact_name": "PM", "contact_email": "pm@test.com",
        "contact_phone": "0910203040",
    })

    await create_user(client, superuser_headers, {
        "email": "owner@permtest.com", "password": "Owner123!",
        "full_name": "Owner", "role": "owner", "tenant_id": td["id"],
    })
    await create_user(client, superuser_headers, {
        "email": "emp@permtest.com", "password": "Emp123!",
        "full_name": "Employee", "role": "employee", "tenant_id": td["id"],
    })

    h_owner = await login_user(client, "owner@permtest.com", "Owner123!")

    up = await client.post(
        "/api/v1/documents/upload", headers=h_owner,
        files={"file": ("test.txt", b"Test content", "text/plain")},
    )
    assert up.status_code == 200
    doc_id = up.json()["id"]

    h_emp = await login_user(client, "emp@permtest.com", "Emp123!")

    assert (await client.delete(f"/api/v1/documents/{doc_id}", headers=h_emp)).status_code == 403
    assert (await client.delete(f"/api/v1/documents/{doc_id}", headers=h_owner)).status_code == 200


@pytest.mark.asyncio
async def test_employee_cannot_view_audit_logs(client: AsyncClient, superuser_headers: dict):
    """測試一般員工無法查看稽核日誌"""

    td = await create_tenant(client, superuser_headers, {
        "name": "Audit Perm Test", "tax_id": "20304050",
        "contact_name": "APM", "contact_email": "apm@test.com",
        "contact_phone": "0920304050",
    })

    await create_user(client, superuser_headers, {
        "email": "admin@ap.com", "password": "Admin123!",
        "full_name": "Admin", "role": "admin", "tenant_id": td["id"],
    })
    await create_user(client, superuser_headers, {
        "email": "emp@ap.com", "password": "Emp123!",
        "full_name": "Emp", "role": "employee", "tenant_id": td["id"],
    })

    h_admin = await login_user(client, "admin@ap.com", "Admin123!")
    h_emp = await login_user(client, "emp@ap.com", "Emp123!")

    assert (await client.get("/api/v1/audit/logs", headers=h_admin)).status_code == 200
    assert (await client.get("/api/v1/audit/logs", headers=h_emp)).status_code == 403


@pytest.mark.asyncio
async def test_employee_cannot_view_usage_reports(client: AsyncClient, superuser_headers: dict):
    """測試一般員工無法查看用量報表"""

    td = await create_tenant(client, superuser_headers, {
        "name": "Usage Perm Test", "tax_id": "30405060",
        "contact_name": "UPM", "contact_email": "upm@test.com",
        "contact_phone": "0930405060",
    })

    await create_user(client, superuser_headers, {
        "email": "owner@up.com", "password": "Owner123!",
        "full_name": "Owner", "role": "owner", "tenant_id": td["id"],
    })
    await create_user(client, superuser_headers, {
        "email": "emp@up.com", "password": "Emp123!",
        "full_name": "Emp", "role": "employee", "tenant_id": td["id"],
    })

    h_owner = await login_user(client, "owner@up.com", "Owner123!")
    h_emp = await login_user(client, "emp@up.com", "Emp123!")

    assert (await client.get("/api/v1/audit/usage/summary", headers=h_owner)).status_code == 200
    assert (await client.get("/api/v1/audit/usage/summary", headers=h_emp)).status_code == 403
    assert (await client.get("/api/v1/audit/usage/records", headers=h_owner)).status_code == 200
    assert (await client.get("/api/v1/audit/usage/records", headers=h_emp)).status_code == 403


@pytest.mark.asyncio
async def test_hr_can_manage_documents_but_not_users(client: AsyncClient, superuser_headers: dict):
    """測試 HR 可以管理文件但無法管理使用者"""

    td = await create_tenant(client, superuser_headers, {
        "name": "HR Perm Test", "tax_id": "40506070",
        "contact_name": "HPM", "contact_email": "hpm@test.com",
        "contact_phone": "0940506070",
    })

    await create_user(client, superuser_headers, {
        "email": "admin@hp.com", "password": "Admin123!",
        "full_name": "Admin", "role": "admin", "tenant_id": td["id"],
    })
    await create_user(client, superuser_headers, {
        "email": "hr@hp.com", "password": "HR123!",
        "full_name": "HR", "role": "hr", "tenant_id": td["id"],
    })

    h_hr = await login_user(client, "hr@hp.com", "HR123!")
    h_admin = await login_user(client, "admin@hp.com", "Admin123!")

    # HR 上傳文件 → 成功
    up = await client.post(
        "/api/v1/documents/upload", headers=h_hr,
        files={"file": ("hr.txt", b"HR doc", "text/plain")},
    )
    assert up.status_code == 200
    doc_id = up.json()["id"]

    assert (await client.get("/api/v1/documents/", headers=h_hr)).status_code == 200
    assert (await client.delete(f"/api/v1/documents/{doc_id}", headers=h_hr)).status_code == 200

    # HR 建使用者 → 拒絕
    r = await client.post("/api/v1/users/", headers=h_hr, json={
        "email": "new@hp.com", "password": "New123!",
        "full_name": "New", "role": "employee", "tenant_id": td["id"],
    })
    assert r.status_code in [403, 401]

    # Admin 建使用者 → 成功
    r2 = await client.post("/api/v1/users/", headers=h_admin, json={
        "email": "new2@hp.com", "password": "New123!",
        "full_name": "New2", "role": "employee", "tenant_id": td["id"],
    })
    assert r2.status_code == 200


@pytest.mark.asyncio
async def test_viewer_read_only_access(client: AsyncClient, superuser_headers: dict):
    """測試 Viewer 角色只有唯讀權限"""

    td = await create_tenant(client, superuser_headers, {
        "name": "Viewer Test Co", "tax_id": "50607080",
        "contact_name": "VTM", "contact_email": "vtm@test.com",
        "contact_phone": "0950607080",
    })

    await create_user(client, superuser_headers, {
        "email": "hr@vt.com", "password": "HR123!",
        "full_name": "HR", "role": "hr", "tenant_id": td["id"],
    })
    await create_user(client, superuser_headers, {
        "email": "viewer@vt.com", "password": "Viewer123!",
        "full_name": "Viewer", "role": "viewer", "tenant_id": td["id"],
    })

    h_hr = await login_user(client, "hr@vt.com", "HR123!")

    up = await client.post(
        "/api/v1/documents/upload", headers=h_hr,
        files={"file": ("vt.txt", b"Test doc", "text/plain")},
    )
    assert up.status_code == 200
    doc_id = up.json()["id"]

    h_viewer = await login_user(client, "viewer@vt.com", "Viewer123!")

    # 讀取 → 成功
    assert (await client.get("/api/v1/documents/", headers=h_viewer)).status_code == 200
    assert (await client.get(f"/api/v1/documents/{doc_id}", headers=h_viewer)).status_code == 200

    # 上傳 → 小會殷回權限檢查，在 Celery 任務之前就會拒絕
    r = await client.post(
        "/api/v1/documents/upload", headers=h_viewer,
        files={"file": ("v.txt", b"Viewer attempt", "text/plain")},
    )
    assert r.status_code == 403

    # 刪除 → 拒絕
    assert (await client.delete(f"/api/v1/documents/{doc_id}", headers=h_viewer)).status_code == 403

    # 聊天 → 成功
    chat = await client.post(CHAT_URL, headers=h_viewer, json={"question": "Viewer Q"})
    assert chat.status_code == 200
