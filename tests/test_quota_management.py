"""
Phase 3 Integration Tests — Quota Management (T3-1)
"""
import pytest
from httpx import AsyncClient
from tests.conftest import create_tenant, create_user, login_user

CHAT_URL = "/api/v1/chat/chat"


async def _setup_tenant(client, superuser_headers, name, tax_id, plan="free"):
    tid = tax_id.lower()  # EmailStr normalizes domain to lowercase
    t = await create_tenant(client, superuser_headers, {
        "name": name, "tax_id": tax_id,
        "contact_name": "C", "contact_email": f"c@{tid}.com",
        "contact_phone": f"09{tax_id}",
        "plan": plan,
    })
    await create_user(client, superuser_headers, {
        "email": f"owner@{tid}.com", "password": "Owner123!",
        "full_name": f"Owner {name}", "role": "owner",
        "tenant_id": t["id"],
    })
    h = await login_user(client, f"owner@{tid}.com", "Owner123!")
    return t, h


# ── T3-1: Quota Management ──

@pytest.mark.asyncio
async def test_tenant_created_with_plan_defaults(client: AsyncClient, superuser_headers: dict):
    """測試建立租戶時自動套用方案預設配額"""
    t, _ = await _setup_tenant(client, superuser_headers, "PlanTest", "QP01", plan="free")

    # 查看配額
    r = await client.get(f"/api/v1/admin/tenants/{t['id']}/quota", headers=superuser_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["max_users"] == 5
    assert data["monthly_query_limit"] == 500
    assert data["is_over_quota"] is False


@pytest.mark.asyncio
async def test_superuser_can_update_quota(client: AsyncClient, superuser_headers: dict):
    """測試超管可以修改租戶配額"""
    t, _ = await _setup_tenant(client, superuser_headers, "QuotaUpd", "QU01")

    r = await client.put(
        f"/api/v1/admin/tenants/{t['id']}/quota",
        headers=superuser_headers,
        json={"max_users": 100, "monthly_query_limit": 10000},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["max_users"] == 100
    assert data["monthly_query_limit"] == 10000


@pytest.mark.asyncio
async def test_apply_plan_quota(client: AsyncClient, superuser_headers: dict):
    """測試套用方案預設配額"""
    t, _ = await _setup_tenant(client, superuser_headers, "PlanApply", "PA01")

    r = await client.post(
        f"/api/v1/admin/tenants/{t['id']}/quota/apply-plan?plan=pro",
        headers=superuser_headers,
    )
    assert r.status_code == 200
    assert r.json()["plan"] == "pro"

    r2 = await client.get(f"/api/v1/admin/tenants/{t['id']}/quota", headers=superuser_headers)
    assert r2.json()["max_users"] == 50
    assert r2.json()["monthly_query_limit"] == 5000


@pytest.mark.asyncio
async def test_query_quota_enforcement(client: AsyncClient, superuser_headers: dict):
    """測試查詢配額強制執行 — 超額時返回 429"""
    t, h = await _setup_tenant(client, superuser_headers, "QuotaEnf", "QE01")

    # 設定極低配額: 1 次查詢
    await client.put(
        f"/api/v1/admin/tenants/{t['id']}/quota",
        headers=superuser_headers,
        json={"monthly_query_limit": 1},
    )

    # 第 1 次查詢應成功
    r1 = await client.post(CHAT_URL, headers=h, json={"question": "第一個問題"})
    assert r1.status_code == 200

    # 第 2 次查詢應被限制
    r2 = await client.post(CHAT_URL, headers=h, json={"question": "第二個問題"})
    assert r2.status_code == 429
    assert "quota_exceeded" in str(r2.json())


@pytest.mark.asyncio
async def test_document_quota_enforcement(client: AsyncClient, superuser_headers: dict):
    """測試文件配額強制執行"""
    t, h = await _setup_tenant(client, superuser_headers, "DocQuota", "DQ01")

    # 設定配額: 1 份文件
    await client.put(
        f"/api/v1/admin/tenants/{t['id']}/quota",
        headers=superuser_headers,
        json={"max_documents": 1},
    )

    # 第 1 份應成功
    r1 = await client.post(
        "/api/v1/documents/upload", headers=h,
        files={"file": ("a.txt", b"hello", "text/plain")},
    )
    assert r1.status_code == 200

    # 第 2 份應被限制
    r2 = await client.post(
        "/api/v1/documents/upload", headers=h,
        files={"file": ("b.txt", b"world", "text/plain")},
    )
    assert r2.status_code == 429


@pytest.mark.asyncio
async def test_list_plan_quotas(client: AsyncClient, superuser_headers: dict):
    """測試列出方案配額"""
    r = await client.get("/api/v1/admin/quota/plans", headers=superuser_headers)
    assert r.status_code == 200
    data = r.json()
    assert "free" in data
    assert "pro" in data
    assert "enterprise" in data
    assert data["pro"]["max_users"] == 50


# ── CG-QUOTA：三軸強制補強（串流主路徑／token 軸／儲存軸／新方案矩陣）──

STREAM_URL = "/api/v1/chat/chat/stream"


@pytest.mark.asyncio
async def test_stream_query_quota_enforcement(client: AsyncClient, superuser_headers: dict):
    """串流主路徑也必須強制查詢配額（CG-QUOTA 補洞：原先只擋非串流 /chat）"""
    t, h = await _setup_tenant(client, superuser_headers, "StreamQ", "SQ01")

    await client.put(
        f"/api/v1/admin/tenants/{t['id']}/quota",
        headers=superuser_headers,
        json={"monthly_query_limit": 0},
    )

    r = await client.post(STREAM_URL, headers=h, json={"question": "串流問題"})
    assert r.status_code == 429
    body = r.json()
    assert "quota_exceeded" in str(body)
    assert body["detail"]["axis"] == "query"


@pytest.mark.asyncio
async def test_stream_token_quota_enforcement(client: AsyncClient, superuser_headers: dict):
    """串流主路徑強制 token 軸"""
    t, h = await _setup_tenant(client, superuser_headers, "StreamT", "ST01")

    await client.put(
        f"/api/v1/admin/tenants/{t['id']}/quota",
        headers=superuser_headers,
        json={"monthly_token_limit": 0},
    )

    r = await client.post(STREAM_URL, headers=h, json={"question": "串流問題"})
    assert r.status_code == 429
    assert r.json()["detail"]["axis"] == "token"


@pytest.mark.asyncio
async def test_token_quota_enforcement_nonstream(client: AsyncClient, superuser_headers: dict):
    """非串流 /chat 也檢查 token 軸"""
    t, h = await _setup_tenant(client, superuser_headers, "TokEnf", "TE01")

    await client.put(
        f"/api/v1/admin/tenants/{t['id']}/quota",
        headers=superuser_headers,
        json={"monthly_token_limit": 0},
    )

    r = await client.post(CHAT_URL, headers=h, json={"question": "問題"})
    assert r.status_code == 429
    assert r.json()["detail"]["axis"] == "token"


@pytest.mark.asyncio
async def test_storage_usage_tracked(client: AsyncClient, superuser_headers: dict):
    """儲存軸：上傳文件後 current_storage_mb 反映 file_size 累計（不再是寫死 0）"""
    t, h = await _setup_tenant(client, superuser_headers, "Storage", "SU01")

    payload = b"x" * (1024 * 1024)  # 1 MB
    r = await client.post(
        "/api/v1/documents/upload", headers=h,
        files={"file": ("big.txt", payload, "text/plain")},
    )
    assert r.status_code == 200

    q = await client.get(f"/api/v1/admin/tenants/{t['id']}/quota", headers=superuser_headers)
    assert q.status_code == 200
    data = q.json()
    assert data["current_storage_mb"] >= 1.0
    assert data["storage_usage_ratio"] is not None


@pytest.mark.asyncio
async def test_new_plan_matrix(client: AsyncClient, superuser_headers: dict):
    """CG-QUOTA 方案矩陣對齊雲端計畫 §3.3：pilot/team/business"""
    r = await client.get("/api/v1/admin/quota/plans", headers=superuser_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["pilot"]["max_users"] == 10
    assert data["pilot"]["max_documents"] == 200
    assert data["pilot"]["monthly_query_limit"] == 500
    assert data["team"]["max_users"] == 50
    assert data["team"]["max_documents"] == 2000
    assert data["team"]["monthly_query_limit"] == 5000
    assert data["business"]["max_users"] == 200
    assert data["business"]["max_documents"] == 20000
    assert data["business"]["monthly_query_limit"] == 50000
    assert data["enterprise"]["monthly_query_limit"] is None


@pytest.mark.asyncio
async def test_tenant_created_with_pilot_defaults(client: AsyncClient, superuser_headers: dict):
    """以 pilot 方案建立租戶時套用新矩陣預設值"""
    t, _ = await _setup_tenant(client, superuser_headers, "PilotPlan", "PP01", plan="pilot")

    r = await client.get(f"/api/v1/admin/tenants/{t['id']}/quota", headers=superuser_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["plan"] == "pilot"
    assert data["max_users"] == 10
    assert data["max_documents"] == 200
    assert data["monthly_query_limit"] == 500


@pytest.mark.asyncio
async def test_storage_quota_enforcement(client: AsyncClient, superuser_headers: dict):
    """儲存軸強制：超過 max_storage_mb 時上傳回 429"""
    t, h = await _setup_tenant(client, superuser_headers, "StorEnf", "SE01")

    await client.put(
        f"/api/v1/admin/tenants/{t['id']}/quota",
        headers=superuser_headers,
        json={"max_storage_mb": 1},
    )

    payload = b"x" * (2 * 1024 * 1024)  # 2 MB
    r = await client.post(
        "/api/v1/documents/upload", headers=h,
        files={"file": ("big.txt", payload, "text/plain")},
    )
    assert r.status_code == 429
    assert r.json()["detail"]["axis"] == "storage"
