"""
Phase 3 Integration Tests — Rate Limiting & Analytics (T3-4, T3-5)
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


# ── T3-5: Cost Analytics ──

@pytest.mark.asyncio
async def test_daily_usage_trend(client: AsyncClient, superuser_headers: dict):
    """測試每日用量趨勢 API"""
    t, h = await _setup(client, superuser_headers, "DT01")

    await client.post(CHAT_URL, headers=h, json={"question": "trend q"})

    r = await client.get("/api/v1/analytics/trends/daily?days=7", headers=superuser_headers)
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    if data:
        assert "date" in data[0]
        assert "queries" in data[0]
        assert "cost" in data[0]


@pytest.mark.asyncio
async def test_daily_trend_per_tenant(client: AsyncClient, superuser_headers: dict):
    """測試單一租戶每日趨勢"""
    t, h = await _setup(client, superuser_headers, "DT02")

    await client.post(CHAT_URL, headers=h, json={"question": "tenant trend"})

    r = await client.get(
        f"/api/v1/analytics/trends/daily?tenant_id={t['id']}&days=7",
        headers=superuser_headers,
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_monthly_cost_by_tenant(client: AsyncClient, superuser_headers: dict):
    """測試各租戶月度成本排行"""
    t, h = await _setup(client, superuser_headers, "MC01")

    await client.post(CHAT_URL, headers=h, json={"question": "cost q"})

    r = await client.get("/api/v1/analytics/trends/monthly-by-tenant", headers=superuser_headers)
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    if data:
        assert "tenant_name" in data[0]
        assert "total_cost" in data[0]


@pytest.mark.asyncio
async def test_anomaly_detection(client: AsyncClient, superuser_headers: dict):
    """測試異常偵測 API"""
    r = await client.get("/api/v1/analytics/anomalies", headers=superuser_headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


@pytest.mark.asyncio
async def test_budget_alerts(client: AsyncClient, superuser_headers: dict):
    """測試預算預警 API"""
    r = await client.get("/api/v1/analytics/budget-alerts", headers=superuser_headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


@pytest.mark.asyncio
async def test_budget_alerts_detects_exceeded(client: AsyncClient, superuser_headers: dict):
    """測試預算預警能偵測超額租戶"""
    t, h = await _setup(client, superuser_headers, "BA01")

    # 設定極低配額
    await client.put(
        f"/api/v1/admin/tenants/{t['id']}/quota",
        headers=superuser_headers,
        json={"monthly_query_limit": 1},
    )

    await client.post(CHAT_URL, headers=h, json={"question": "q"})

    r = await client.get("/api/v1/analytics/budget-alerts", headers=superuser_headers)
    assert r.status_code == 200
    data = r.json()
    # 應有至少一個此租戶的告警
    tenant_alerts = [a for a in data if a["tenant_id"] == t["id"]]
    assert len(tenant_alerts) >= 1
    assert tenant_alerts[0]["alert_type"] in ("warning", "exceeded")


# ── T3-3: Security Isolation Config ──

@pytest.mark.asyncio
async def test_get_default_security_config(client: AsyncClient, superuser_headers: dict):
    """測試取得預設安全組態"""
    t, _ = await _setup(client, superuser_headers, "SC01")

    r = await client.get(f"/api/v1/admin/tenants/{t['id']}/security", headers=superuser_headers)
    assert r.status_code == 200
    assert r.json()["isolation_level"] == "standard"


@pytest.mark.asyncio
async def test_update_security_config(client: AsyncClient, superuser_headers: dict):
    """測試更新安全組態"""
    t, _ = await _setup(client, superuser_headers, "SC02")

    r = await client.put(
        f"/api/v1/admin/tenants/{t['id']}/security",
        headers=superuser_headers,
        json={
            "isolation_level": "enhanced",
            "require_mfa": True,
            "ip_whitelist": "192.168.1.0/24,10.0.0.0/8",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["isolation_level"] == "enhanced"
    assert data["require_mfa"] is True
    assert "192.168.1.0" in data["ip_whitelist"]


@pytest.mark.asyncio
async def test_invalid_isolation_level_rejected(client: AsyncClient, superuser_headers: dict):
    """測試無效隔離等級被拒絕"""
    t, _ = await _setup(client, superuser_headers, "SC03")

    r = await client.put(
        f"/api/v1/admin/tenants/{t['id']}/security",
        headers=superuser_headers,
        json={"isolation_level": "invalid_level"},
    )
    assert r.status_code == 400
