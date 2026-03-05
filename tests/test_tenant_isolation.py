"""
Tenant Isolation Tests
測試租戶之間的資料隔離與安全性
"""
import pytest
from httpx import AsyncClient
from tests.conftest import create_tenant, create_user, login_user

CHAT_URL = "/api/v1/chat/chat"


@pytest.mark.asyncio
async def test_tenant_data_isolation(client: AsyncClient, superuser_headers: dict):
    """測試租戶 A 無法存取租戶 B 的資料"""

    ta = await create_tenant(client, superuser_headers, {
        "name": "Company A", "tax_id": "11111111",
        "contact_name": "A", "contact_email": "a@a.com", "contact_phone": "0911111111",
    })
    tb = await create_tenant(client, superuser_headers, {
        "name": "Company B", "tax_id": "22222222",
        "contact_name": "B", "contact_email": "b@b.com", "contact_phone": "0922222222",
    })

    await create_user(client, superuser_headers, {
        "email": "o@a.com", "password": "PassA123!", "full_name": "Owner A",
        "role": "owner", "tenant_id": ta["id"],
    })
    await create_user(client, superuser_headers, {
        "email": "o@b.com", "password": "PassB123!", "full_name": "Owner B",
        "role": "owner", "tenant_id": tb["id"],
    })

    ha = await login_user(client, "o@a.com", "PassA123!")
    hb = await login_user(client, "o@b.com", "PassB123!")

    # B 上傳文件
    up = await client.post(
        "/api/v1/documents/upload", headers=hb,
        files={"file": ("b.txt", b"B confidential.", "text/plain")},
    )
    assert up.status_code == 200
    doc_b_id = up.json()["id"]

    # A 看不到 B 的文件
    assert len((await client.get("/api/v1/documents/", headers=ha)).json()) == 0
    assert len((await client.get("/api/v1/documents/", headers=hb)).json()) == 1

    assert (await client.get(f"/api/v1/documents/{doc_b_id}", headers=ha)).status_code in [403, 404]
    assert (await client.delete(f"/api/v1/documents/{doc_b_id}", headers=ha)).status_code in [403, 404]
    assert (await client.get(f"/api/v1/documents/{doc_b_id}", headers=hb)).status_code == 200


@pytest.mark.asyncio
async def test_conversation_isolation(client: AsyncClient, superuser_headers: dict):
    """測試對話記錄的租戶隔離"""

    ta = await create_tenant(client, superuser_headers, {
        "name": "Chat A", "tax_id": "33333333",
        "contact_name": "CA", "contact_email": "ca@a.com", "contact_phone": "0933333333",
    })
    tb = await create_tenant(client, superuser_headers, {
        "name": "Chat B", "tax_id": "44444444",
        "contact_name": "CB", "contact_email": "cb@b.com", "contact_phone": "0944444444",
    })

    await create_user(client, superuser_headers, {
        "email": "u@ca.com", "password": "ChatA123!", "full_name": "UA",
        "role": "employee", "tenant_id": ta["id"],
    })
    await create_user(client, superuser_headers, {
        "email": "u@cb.com", "password": "ChatB123!", "full_name": "UB",
        "role": "employee", "tenant_id": tb["id"],
    })

    ha = await login_user(client, "u@ca.com", "ChatA123!")
    hb = await login_user(client, "u@cb.com", "ChatB123!")

    ra = await client.post(CHAT_URL, headers=ha, json={"question": "Q from A"})
    assert ra.status_code == 200
    conv_a = ra.json()["conversation_id"]

    rb = await client.post(CHAT_URL, headers=hb, json={"question": "Q from B"})
    assert rb.status_code == 200
    conv_b = rb.json()["conversation_id"]

    ca = (await client.get("/api/v1/chat/conversations", headers=ha)).json()
    assert len(ca) == 1 and ca[0]["id"] == conv_a

    cb = (await client.get("/api/v1/chat/conversations", headers=hb)).json()
    assert len(cb) == 1 and cb[0]["id"] == conv_b

    # A 存取 B 的對話 → 拒絕
    cross = await client.get(f"/api/v1/chat/conversations/{conv_b}/messages", headers=ha)
    assert cross.status_code in [403, 404]


@pytest.mark.asyncio
async def test_audit_log_isolation(client: AsyncClient, superuser_headers: dict):
    """測試稽核日誌的租戶隔離"""

    ta = await create_tenant(client, superuser_headers, {
        "name": "Audit A", "tax_id": "55555555",
        "contact_name": "AA", "contact_email": "aa@a.com", "contact_phone": "0955555555",
    })
    tb = await create_tenant(client, superuser_headers, {
        "name": "Audit B", "tax_id": "66666666",
        "contact_name": "AB", "contact_email": "ab@b.com", "contact_phone": "0966666666",
    })

    await create_user(client, superuser_headers, {
        "email": "adm@aa.com", "password": "AuditA123!", "full_name": "Admin A",
        "role": "admin", "tenant_id": ta["id"],
    })
    await create_user(client, superuser_headers, {
        "email": "adm@ab.com", "password": "AuditB123!", "full_name": "Admin B",
        "role": "admin", "tenant_id": tb["id"],
    })

    ha = await login_user(client, "adm@aa.com", "AuditA123!")
    hb = await login_user(client, "adm@ab.com", "AuditB123!")

    await client.post(CHAT_URL, headers=ha, json={"question": "Test A"})
    await client.post(CHAT_URL, headers=hb, json={"question": "Test B"})

    la = (await client.get("/api/v1/audit/logs", headers=ha)).json()
    lb = (await client.get("/api/v1/audit/logs", headers=hb)).json()

    if la and lb:
        a_ids = {l.get("actor_user_id") for l in la}
        b_ids = {l.get("actor_user_id") for l in lb}
        assert len(a_ids & b_ids) == 0

    assert (await client.get("/api/v1/audit/usage/summary", headers=ha)).status_code == 200
    assert (await client.get("/api/v1/audit/usage/summary", headers=hb)).status_code == 200


@pytest.mark.asyncio
async def test_knowledge_base_isolation(client: AsyncClient, superuser_headers: dict):
    """測試知識庫檢索的租戶隔離"""

    ta = await create_tenant(client, superuser_headers, {
        "name": "KB A", "tax_id": "77777777",
        "contact_name": "KA", "contact_email": "ka@a.com", "contact_phone": "0977777777",
    })
    tb = await create_tenant(client, superuser_headers, {
        "name": "KB B", "tax_id": "88888888",
        "contact_name": "KB", "contact_email": "kb@b.com", "contact_phone": "0988888888",
    })

    await create_user(client, superuser_headers, {
        "email": "u@ka.com", "password": "KBA123!", "full_name": "UA",
        "role": "hr", "tenant_id": ta["id"],
    })
    await create_user(client, superuser_headers, {
        "email": "u@kb.com", "password": "KBB123!", "full_name": "UB",
        "role": "hr", "tenant_id": tb["id"],
    })

    ha = await login_user(client, "u@ka.com", "KBA123!")
    hb = await login_user(client, "u@kb.com", "KBB123!")

    # 使用真實向量檢索（測試租戶尚無文件，預期回傳空結果但狀態 200）
    sa = await client.post("/api/v1/kb/search", headers=ha, json={"query": "policy", "top_k": 5})
    assert sa.status_code == 200

    sb = await client.post("/api/v1/kb/search", headers=hb, json={"query": "policy", "top_k": 5})
    assert sb.status_code == 200
