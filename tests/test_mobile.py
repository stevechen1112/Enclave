"""
Mobile API Tests — /api/v1/mobile
測試 Token 刷新、Token 撤銷、Push Token 註冊、安全事件、憑證指紋
"""
import pytest
from httpx import AsyncClient
from tests.conftest import create_tenant, create_user, login_user


async def _user_setup(client, superuser_headers, suffix):
    t = await create_tenant(client, superuser_headers, {"name": f"MobCo {suffix}"})
    await create_user(client, superuser_headers, {
        "email": f"emp@mob{suffix}.com", "password": "Emp123!",
        "full_name": "Emp", "role": "employee", "tenant_id": t["id"],
    })
    h = await login_user(client, f"emp@mob{suffix}.com", "Emp123!")

    # 取得原始 token（從登入回應）
    login_resp = await client.post(
        "/api/v1/auth/login/access-token",
        data={"username": f"emp@mob{suffix}.com", "password": "Emp123!"},
    )
    token = login_resp.json()["access_token"]
    return h, token


@pytest.mark.asyncio
async def test_refresh_token(client: AsyncClient, superuser_headers: dict):
    """POST /mobile/auth/refresh-token 應回傳新 token"""
    h, token = await _user_setup(client, superuser_headers, "rf")

    resp = await client.post(
        "/api/v1/mobile/auth/refresh-token",
        headers=h,
        json={"token": token},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data


@pytest.mark.asyncio
async def test_revoke_token(client: AsyncClient, superuser_headers: dict):
    """POST /mobile/auth/revoke-token 應成功（204）"""
    h, token = await _user_setup(client, superuser_headers, "rv")

    resp = await client.post(
        "/api/v1/mobile/auth/revoke-token",
        headers=h,
        json={"token": token},
    )
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_register_push_token(client: AsyncClient, superuser_headers: dict):
    """POST /mobile/users/me/push-token 應成功（204）"""
    h, _ = await _user_setup(client, superuser_headers, "pt")

    resp = await client.post(
        "/api/v1/mobile/users/me/push-token",
        headers=h,
        json={
            "push_token": "ExponentPushToken[xxxxxxxxxxxxxxxxxxxx]",
            "device_platform": "ios",
        },
    )
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_report_security_event(client: AsyncClient, superuser_headers: dict):
    """POST /mobile/security/events 應成功（204）"""
    h, _ = await _user_setup(client, superuser_headers, "se")

    resp = await client.post(
        "/api/v1/mobile/security/events",
        headers=h,
        json={
            "event_type": "screenshot_attempt",
            "device_id": "device-test-001",
            "metadata": {"screen": "ChatPage"},
        },
    )
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_get_cert_fingerprint(client: AsyncClient, superuser_headers: dict):
    """GET /mobile/security/cert-fingerprint 應回傳憑證指紋"""
    h, _ = await _user_setup(client, superuser_headers, "cf")

    resp = await client.get("/api/v1/mobile/security/cert-fingerprint", headers=h)
    assert resp.status_code == 200
    data = resp.json()
    assert "fingerprint" in data or "sha256" in data or "cert" in str(data).lower()


@pytest.mark.asyncio
async def test_unauthenticated_mobile_rejected(client: AsyncClient):
    """未登入不得存取 mobile API"""
    resp = await client.post(
        "/api/v1/mobile/auth/refresh-token",
        json={"token": "fake"},
    )
    assert resp.status_code == 401
