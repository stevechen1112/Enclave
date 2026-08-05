"""CG-AUTH-SSO 測試：TOTP、MFA 登入挑戰、email 驗證、SSO 登入閉環。

涵蓋計畫驗收三點：
- SSO 登入 → JWT 含正確 tenant
- 未驗證不可聊天（EMAIL_VERIFICATION_ENABLED 時）
- MFA 挑戰不可繞（partial token 被所有受保護 API 拒絕）
"""
import time

import pytest
from httpx import AsyncClient

from app.core import security
from app.services import totp
from app.services.emailer import make_verification_token, parse_verification_token
from tests.conftest import create_tenant, create_user, login_user

LOGIN_URL = "/api/v1/auth/login/access-token"
CHAT_URL = "/api/v1/chat/chat"


async def _setup(client, superuser_headers, name, tax_id, plan="team"):
    tid = tax_id.lower()
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


def _set_user_flag(test_engine, email: str, **fields):
    from sqlalchemy.orm import sessionmaker

    from app.models.user import User

    S = sessionmaker(bind=test_engine)
    db = S()
    try:
        u = db.query(User).filter(User.email == email).first()
        assert u is not None, f"user {email} not found"
        for k, v in fields.items():
            setattr(u, k, v)
        db.commit()
    finally:
        db.close()


# ── TOTP 單元測試 ─────────────────────────────────────────────


class TestTotp:
    def test_roundtrip(self):
        secret = totp.generate_secret()
        code = totp.totp_at(secret, time.time())
        assert totp.verify(secret, code)

    def test_wrong_code_rejected(self):
        secret = totp.generate_secret()
        assert not totp.verify(secret, "000000") or totp.totp_at(secret, time.time()) == "000000"

    def test_window_tolerance(self):
        secret = totp.generate_secret()
        now = time.time()
        prev_code = totp.totp_at(secret, now - 30)
        assert totp.verify(secret, prev_code, at=now)

    def test_garbage_rejected(self):
        secret = totp.generate_secret()
        assert not totp.verify(secret, "abcdef")
        assert not totp.verify(secret, "")
        assert not totp.verify("", "123456")

    def test_provisioning_uri(self):
        uri = totp.provisioning_uri("ABC123", email="a@b.com")
        assert uri.startswith("otpauth://totp/")
        assert "secret=ABC123" in uri


# ── 局部 token 不可繞過 ───────────────────────────────────────


class TestPartialToken:
    def test_partial_token_roundtrip(self):
        token = security.create_partial_token(
            "a@b.com", scope=security.SCOPE_MFA_PENDING, tenant_id="00000000-0000-0000-0000-000000000000"
        )
        payload = security.decode_partial_token(token, expected_scope=security.SCOPE_MFA_PENDING)
        assert payload and payload["sub"] == "a@b.com"

    def test_partial_token_scope_mismatch(self):
        token = security.create_partial_token("a@b.com", scope=security.SCOPE_MFA_PENDING)
        assert security.decode_partial_token(token, expected_scope=security.SCOPE_MFA_ENROLL) is None

    def test_full_token_not_accepted_as_partial(self):
        full = security.create_access_token("a@b.com")
        assert security.decode_partial_token(full) is None

    def test_invalid_scope_rejected(self):
        with pytest.raises(ValueError):
            security.create_partial_token("a@b.com", scope="admin")

    @pytest.mark.asyncio
    async def test_partial_token_rejected_by_protected_api(
        self, client: AsyncClient, superuser_headers: dict
    ):
        """MFA 挑戰不可繞：partial token 打任何受保護 API 必須 403。"""
        t, _ = await _setup(client, superuser_headers, "PartialT", "PT01")
        partial = security.create_partial_token(
            "owner@pt01.com", scope=security.SCOPE_MFA_PENDING, tenant_id=t["id"]
        )
        r = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {partial}"})
        assert r.status_code == 403


# ── MFA 登入流程 ──────────────────────────────────────────────


class TestMfaFlow:
    @pytest.mark.asyncio
    async def test_full_mfa_lifecycle(self, client: AsyncClient, superuser_headers: dict):
        t, h = await _setup(client, superuser_headers, "MfaFlow", "MF01")

        # setup 取得 secret
        r = await client.post("/api/v1/auth/mfa/setup", headers=h)
        assert r.status_code == 200
        secret = r.json()["secret"]
        assert "otpauth://" in r.json()["provisioning_uri"]

        # 錯誤碼不可啟用
        bad = await client.post("/api/v1/auth/mfa/enable", headers=h, json={"code": "999999"})
        assert bad.status_code == 400

        # 正確碼啟用
        code = totp.totp_at(secret, time.time())
        r2 = await client.post("/api/v1/auth/mfa/enable", headers=h, json={"code": code})
        assert r2.status_code == 200

        # 登入改走 MFA 挑戰：不給完整 token
        r3 = await client.post(
            LOGIN_URL, data={"username": "owner@mf01.com", "password": "Owner123!"}
        )
        assert r3.status_code == 200
        body = r3.json()
        assert body.get("mfa_required") is True
        assert "access_token" not in body
        partial = body["partial_token"]

        # partial token 不可呼叫受保護 API
        blocked = await client.get(
            "/api/v1/users/me", headers={"Authorization": f"Bearer {partial}"}
        )
        assert blocked.status_code == 403

        # 錯誤 TOTP 不可通過
        bad_verify = await client.post(
            "/api/v1/auth/mfa/verify", json={"partial_token": partial, "code": "000000"}
        )
        assert bad_verify.status_code in (400, 403)

        # 正確 TOTP → 完整 token
        code2 = totp.totp_at(secret, time.time())
        r4 = await client.post(
            "/api/v1/auth/mfa/verify", json={"partial_token": partial, "code": code2}
        )
        assert r4.status_code == 200
        full = r4.json()["access_token"]
        me = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {full}"})
        assert me.status_code == 200

    @pytest.mark.asyncio
    async def test_mfa_enroll_forced_for_owner(
        self, client: AsyncClient, superuser_headers: dict, monkeypatch
    ):
        from app.config import settings

        # 先建好租戶與 owner（此時旗標未開，_setup 內的 login 不受影響），再開強制旗標
        t, _ = await _setup(client, superuser_headers, "MfaForce", "MFE01")
        monkeypatch.setattr(settings, "MFA_ENFORCE_OWNER", True)

        # owner 未設 MFA → 只給 mfa_enroll 局部 token
        r = await client.post(
            LOGIN_URL, data={"username": "owner@mfe01.com", "password": "Owner123!"}
        )
        body = r.json()
        assert body.get("mfa_enroll_required") is True
        partial = body["partial_token"]

        # enroll 局部 token 一樣不可呼叫受保護 API
        blocked = await client.get(
            "/api/v1/users/me", headers={"Authorization": f"Bearer {partial}"}
        )
        assert blocked.status_code == 403

        # 用局部 token 走 setup → enable → 直接拿完整 token
        setup = await client.post(
            f"/api/v1/auth/mfa/setup?partial_token={partial}"
        )
        assert setup.status_code == 200
        secret = setup.json()["secret"]
        code = totp.totp_at(secret, time.time())
        enabled = await client.post(
            f"/api/v1/auth/mfa/enable?partial_token={partial}", json={"code": code}
        )
        assert enabled.status_code == 200
        full = enabled.json()["access_token"]
        me = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {full}"})
        assert me.status_code == 200


# ── Email 驗證 ────────────────────────────────────────────────


class TestEmailVerification:
    def test_token_roundtrip(self):
        token = make_verification_token("a@b.com")
        assert parse_verification_token(token) == "a@b.com"

    def test_token_tampered(self):
        token = make_verification_token("a@b.com")
        assert parse_verification_token(token[:-2] + "zz") is None

    @pytest.mark.asyncio
    async def test_verify_email_endpoint(self, client: AsyncClient, superuser_headers: dict, test_engine):
        t, h = await _setup(client, superuser_headers, "EmailV", "EV01")
        _set_user_flag(test_engine, "owner@ev01.com", email_verified=False)

        token = make_verification_token("owner@ev01.com")
        r = await client.post("/api/v1/auth/verify-email", json={"token": token})
        assert r.status_code == 200
        assert r.json()["email_verified"] is True

    @pytest.mark.asyncio
    async def test_unverified_cannot_chat_when_enabled(
        self, client: AsyncClient, superuser_headers: dict, test_engine, monkeypatch
    ):
        from app.config import settings

        monkeypatch.setattr(settings, "EMAIL_VERIFICATION_ENABLED", True)
        t, h = await _setup(client, superuser_headers, "EmailGate", "EG01")
        _set_user_flag(test_engine, "owner@eg01.com", email_verified=False)

        r = await client.post(CHAT_URL, headers=h, json={"question": "測試問題"})
        assert r.status_code == 403
        assert "email_not_verified" in str(r.json())

        # 驗證後可聊天（可能因 LLM 等後續環節失敗，但不得再是 email_not_verified 403）
        token = make_verification_token("owner@eg01.com")
        await client.post("/api/v1/auth/verify-email", json={"token": token})
        r2 = await client.post(CHAT_URL, headers=h, json={"question": "測試問題"})
        assert not (r2.status_code == 403 and "email_not_verified" in str(r2.json()))

    @pytest.mark.asyncio
    async def test_unverified_can_chat_when_disabled(
        self, client: AsyncClient, superuser_headers: dict, test_engine, monkeypatch
    ):
        """預設（旗標關閉）不影響既有行為——向後相容。"""
        from app.config import settings

        monkeypatch.setattr(settings, "EMAIL_VERIFICATION_ENABLED", False)
        t, h = await _setup(client, superuser_headers, "EmailOff", "EO01")
        _set_user_flag(test_engine, "owner@eo01.com", email_verified=False)

        r = await client.post(CHAT_URL, headers=h, json={"question": "測試問題"})
        assert not (r.status_code == 403 and "email_not_verified" in str(r.json()))


# ── SSO 登入閉環 ──────────────────────────────────────────────


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = str(self._payload)

    def json(self):
        return self._payload


class _FakeAsyncClient:
    """模擬 token exchange 的 AsyncClient。"""

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, data=None):
        return _FakeResponse(200, {"access_token": "fake-idp-token", "token_type": "Bearer"})


class _FakeSyncClient:
    """模擬 userinfo 的同步 Client。email 以類別屬性注入。"""

    email = "owner@sso01.com"

    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, headers=None):
        return _FakeResponse(200, {"email": type(self).email, "email_verified": True})


class TestSsoLogin:
    async def _make_sso_tenant(self, client, superuser_headers, monkeypatch, tax_id="SSO01", name="SsoCo"):
        monkeypatch.setattr(
            "app.api.v1.endpoints.sso.httpx.AsyncClient", _FakeAsyncClient
        )
        monkeypatch.setattr(
            "app.api.v1.endpoints.sso.httpx.Client", _FakeSyncClient
        )
        t, h = await _setup(client, superuser_headers, name, tax_id)
        # owner 設定 SSO（email 網域白名單 {tax_id}.com）
        domain = f"{tax_id.lower()}.com"
        _FakeSyncClient.email = f"owner@{domain}"
        r = await client.put(
            "/api/v1/sso/config/google",
            headers=h,
            json={
                "provider": "google",
                "client_id": "cid",
                "client_secret": "csecret",
                "redirect_uri": "http://localhost/cb",
                "allowed_domains": [domain],
                "auto_create_user": False,
            },
        )
        assert r.status_code == 200
        return t, h, domain

    @pytest.mark.asyncio
    async def test_sso_login_issues_jwt_with_correct_tenant(
        self, client: AsyncClient, superuser_headers: dict, monkeypatch
    ):
        t, h, domain = await self._make_sso_tenant(client, superuser_headers, monkeypatch)

        # 1. 取 state
        st = await client.post("/api/v1/sso/state", json={"tenant_id": t["id"], "provider": "google"})
        assert st.status_code == 200
        state = st.json()["state"]

        # 2. callback → Enclave JWT
        cb = await client.post(
            "/api/v1/sso/callback",
            json={
                "code": "authcode",
                "redirect_uri": "http://localhost/cb",
                "tenant_id": t["id"],
                "provider": "google",
                "state": state,
                "code_verifier": "verifier",
            },
        )
        assert cb.status_code == 200
        token = cb.json()["access_token"]

        # 3. JWT 含正確 tenant
        from jose import jwt as jose_jwt
        from app.config import settings as _s

        payload = jose_jwt.decode(token, _s.SECRET_KEY, algorithms=[_s.ALGORITHM])
        assert payload["tenant_id"] == t["id"]
        assert payload["sub"] == f"owner@{domain}"

        # 4. token 實際可用
        me = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200

    @pytest.mark.asyncio
    async def test_sso_state_without_config_404(self, client: AsyncClient, superuser_headers: dict):
        t, _ = await _setup(client, superuser_headers, "SsoNone", "SN01")
        r = await client.post("/api/v1/sso/state", json={"tenant_id": t["id"], "provider": "google"})
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_sso_unlinked_email_403(
        self, client: AsyncClient, superuser_headers: dict, monkeypatch
    ):
        """auto_create_user=False 時，未知 email 不得登入（fail-closed）。"""
        t, h, domain = await self._make_sso_tenant(
            client, superuser_headers, monkeypatch, tax_id="SSO02", name="SsoUnlinked"
        )

        class _UnknownEmailClient(_FakeSyncClient):
            email = f"stranger@{domain}"

        monkeypatch.setattr("app.api.v1.endpoints.sso.httpx.Client", _UnknownEmailClient)

        st = await client.post("/api/v1/sso/state", json={"tenant_id": t["id"], "provider": "google"})
        cb = await client.post(
            "/api/v1/sso/callback",
            json={
                "code": "authcode", "redirect_uri": "http://localhost/cb",
                "tenant_id": t["id"], "provider": "google",
                "state": st.json()["state"], "code_verifier": "verifier",
            },
        )
        assert cb.status_code == 403
        assert "sso_account_not_linked" in str(cb.json())

    @pytest.mark.asyncio
    async def test_sso_domain_not_allowed_403(
        self, client: AsyncClient, superuser_headers: dict, monkeypatch
    ):
        t, h, domain = await self._make_sso_tenant(
            client, superuser_headers, monkeypatch, tax_id="SSO03", name="SsoDomain"
        )

        class _OtherDomainClient(_FakeSyncClient):
            email = "x@evil.com"

        monkeypatch.setattr("app.api.v1.endpoints.sso.httpx.Client", _OtherDomainClient)

        st = await client.post("/api/v1/sso/state", json={"tenant_id": t["id"], "provider": "google"})
        cb = await client.post(
            "/api/v1/sso/callback",
            json={
                "code": "authcode", "redirect_uri": "http://localhost/cb",
                "tenant_id": t["id"], "provider": "google",
                "state": st.json()["state"], "code_verifier": "verifier",
            },
        )
        assert cb.status_code == 403

    @pytest.mark.asyncio
    async def test_sso_state_tampered_400(self, client: AsyncClient, superuser_headers: dict, monkeypatch):
        t, h, domain = await self._make_sso_tenant(
            client, superuser_headers, monkeypatch, tax_id="SSO04", name="SsoTampered"
        )
        cb = await client.post(
            "/api/v1/sso/callback",
            json={
                "code": "authcode", "redirect_uri": "http://localhost/cb",
                "tenant_id": t["id"], "provider": "google",
                "state": "forged.state", "code_verifier": "verifier",
            },
        )
        assert cb.status_code == 400

    @pytest.mark.asyncio
    async def test_sso_config_requires_owner(self, client: AsyncClient, superuser_headers: dict):
        """非 owner/admin 不可設定 SSO。"""
        t, h = await _setup(client, superuser_headers, "SsoRole", "SR01")
        await create_user(client, superuser_headers, {
            "email": "emp@sr01.com", "password": "Emp12345!",
            "full_name": "Emp", "role": "employee",
            "tenant_id": t["id"],
        })
        eh = await login_user(client, "emp@sr01.com", "Emp12345!")
        r = await client.put(
            "/api/v1/sso/config/google",
            headers=eh,
            json={"provider": "google", "client_id": "c", "client_secret": "s", "redirect_uri": "http://localhost/cb"},
        )
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_sso_respects_mfa(
        self, client: AsyncClient, superuser_headers: dict, test_engine, monkeypatch
    ):
        """SSO callback 不可繞過 MFA——已啟用 TOTP 的帳號只拿 partial token。"""
        t, h, _ = await self._make_sso_tenant(
            client, superuser_headers, monkeypatch, tax_id="SSO05", name="SsoMfa"
        )
        _set_user_flag(test_engine, "owner@sso05.com", mfa_enabled=True, mfa_secret="JBSWY3DPEHPK3PXP")

        st = await client.post("/api/v1/sso/state", json={"tenant_id": t["id"], "provider": "google"})
        cb = await client.post(
            "/api/v1/sso/callback",
            json={
                "code": "authcode", "redirect_uri": "http://localhost/cb",
                "tenant_id": t["id"], "provider": "google",
                "state": st.json()["state"], "code_verifier": "verifier",
            },
        )
        assert cb.status_code == 200
        body = cb.json()
        assert body.get("mfa_required") is True
        assert "access_token" not in body
        assert body.get("partial_token")


class TestSsoSchemaDefaults:
    def test_auto_create_user_defaults_false(self):
        from app.schemas.sso import SSOConfigCreate

        cfg = SSOConfigCreate(
            provider="google", client_id="c", client_secret="s", redirect_uri="http://localhost/cb"
        )
        assert cfg.auto_create_user is False


class TestMicrosoftEmail:
    def test_rejects_ext_guest_upn_only(self, monkeypatch):
        from app.api.v1.endpoints import sso as sso_mod

        class _ExtClient:
            def __init__(self, *a, **kw):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def get(self, url, headers=None):
                return _FakeResponse(200, {
                    "userPrincipalName": "user_gmail.com#EXT#@tenant.onmicrosoft.com",
                })

        monkeypatch.setattr(sso_mod.httpx, "Client", _ExtClient)
        assert sso_mod._fetch_idp_email("microsoft", {"access_token": "t"}) is None

    def test_accepts_verified_mail(self, monkeypatch):
        from app.api.v1.endpoints import sso as sso_mod

        class _MailClient:
            def __init__(self, *a, **kw):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def get(self, url, headers=None):
                return _FakeResponse(200, {"mail": "User@Corp.com"})

        monkeypatch.setattr(sso_mod.httpx, "Client", _MailClient)
        assert sso_mod._fetch_idp_email("microsoft", {"access_token": "t"}) == "user@corp.com"


class TestEmailerSecurity:
    def test_no_token_in_log_when_smtp_disabled(self, monkeypatch, caplog):
        from app.config import settings
        from app.services import emailer

        monkeypatch.setattr(settings, "SMTP_HOST", "")
        caplog.set_level("WARNING")
        emailer.send_verification_email("a@b.com")
        combined = " ".join(r.message for r in caplog.records)
        assert "verify-email?token=" not in combined
        assert "a@b.com" in combined
