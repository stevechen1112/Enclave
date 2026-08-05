"""SSO endpoints — state & PKCE helpers, OAuth callback → Enclave JWT（CG-AUTH-SSO）。

安全邊界（fail-closed）：
- state 為 HMAC 簽章且 10 分鐘過期，callback 必須 tenant/provider 一致
- allowed_domains 非空時，IdP 回傳 email 網域不在清單 → 403
- 預設不自動開戶（auto_create_user=False）：email 無對應既有帳號 → 403
- 帳號 tenant_id 與 state tenant_id 不一致 → 403（防跨租戶帳號連結攻擊）
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.api.deps import get_db, get_current_active_user
from app.core import security
from app.crud import crud_user
from app.models.tenant import TenantSSOConfig
from app.models.user import User
from app.schemas.sso import (
    OAuthCallbackRequest,
    SSOConfigCreate,
    SSOConfigPublic,
    SSOStateRequest,
    SSOStateResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ── internal helpers ────────────────────────────────────────────

def _sign_state(payload: dict) -> str:
    """Create an HMAC-signed, base64url-encoded state token."""
    data = json.dumps(payload, sort_keys=True).encode()
    sig = hmac.new(settings.SECRET_KEY.encode(), data, hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(data).decode() + "." + sig


def _verify_state(token: str) -> Optional[dict]:
    """Verify and decode a state token.  Returns None on failure."""
    try:
        parts = token.rsplit(".", 1)
        if len(parts) != 2:
            return None
        data_b64, sig = parts
        data = base64.urlsafe_b64decode(data_b64)
        expected_sig = hmac.new(
            settings.SECRET_KEY.encode(), data, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return None
        payload = json.loads(data)
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None


def _get_cfg(db: Session, tenant_id, provider: str) -> Optional[TenantSSOConfig]:
    return (
        db.query(TenantSSOConfig)
        .filter(
            TenantSSOConfig.tenant_id == tenant_id,
            TenantSSOConfig.provider == provider,
            TenantSSOConfig.enabled.is_(True),
        )
        .first()
    )


def _fetch_idp_email(provider: str, tokens: dict) -> Optional[str]:
    """以 access_token 向 IdP 取已驗證 email。取不到回傳 None。"""
    access_token = tokens.get("access_token")
    if not access_token:
        return None
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        with httpx.Client(timeout=20.0) as client:
            if provider == "google":
                resp = client.get(
                    "https://openidconnect.googleapis.com/v1/userinfo", headers=headers
                )
                if resp.status_code != 200:
                    return None
                info = resp.json()
                # Google 明確回報 email 是否已驗證；未驗證不接受
                if info.get("email_verified") is False:
                    return None
                return info.get("email")
            if provider in ("microsoft", "azure"):
                resp = client.get("https://graph.microsoft.com/v1.0/me", headers=headers)
                if resp.status_code != 200:
                    return None
                info = resp.json()
                # fail-closed：只接受 Azure AD 已設定的 mail（通常已驗證）；
                # 不接受僅有 UPN／#EXT# 來賓身分——與 Google email_verified 對齊
                mail = info.get("mail")
                if mail and "@" in mail:
                    return mail.strip().lower()
                upn = (info.get("userPrincipalName") or "").strip()
                if upn and "@" in upn and "#EXT#" not in upn.upper():
                    return upn.lower()
                return None
    except Exception:
        logger.exception("SSO userinfo 取得失敗（provider=%s）", provider)
    return None


# ── endpoints ───────────────────────────────────────────────────

@router.post("/state", response_model=SSOStateResponse)
def create_sso_state(
    body: SSOStateRequest,
    db: Session = Depends(get_db),
) -> SSOStateResponse:
    """Generate HMAC-signed state token for SSO login redirect.

    Verifies that the requested provider is enabled for the tenant
    before issuing a state token.
    """
    # 登入前呼叫、無租戶 context：RLS 下需 bypass 才能讀 SSO 設定
    from app.services.rls import apply_rls_bypass

    apply_rls_bypass(db)
    cfg = _get_cfg(db, body.tenant_id, body.provider)
    if cfg is None:
        raise HTTPException(status_code=404, detail="SSO provider not found or not enabled")

    state_payload = {
        "tenant_id": str(body.tenant_id),
        "provider": body.provider,
        "exp": int(time.time()) + 600,  # 10 min
    }
    token = _sign_state(state_payload)
    return SSOStateResponse(state=token)


@router.post("/callback")
async def sso_callback(
    body: OAuthCallbackRequest,
    db: Session = Depends(get_db),
) -> dict:
    """Handle OAuth callback — verify state, exchange code, issue Enclave JWT."""
    from app.services.rls import apply_rls_bypass

    # 1. Verify state token
    state_data = _verify_state(body.state)
    if state_data is None:
        raise HTTPException(status_code=400, detail="Invalid or expired state")

    # 2. Ensure state matches request parameters
    if state_data.get("tenant_id") != str(body.tenant_id):
        raise HTTPException(status_code=400, detail="State tenant mismatch")
    if state_data.get("provider") != body.provider:
        raise HTTPException(status_code=400, detail="State provider mismatch")

    # 3. PKCE: code_verifier is required
    if not body.code_verifier:
        raise HTTPException(status_code=400, detail="code_verifier is required for PKCE")

    # 4. Exchange authorization code
    apply_rls_bypass(db)  # 登入前流程，讀 SSO 設定與 user 皆需 bypass
    cfg = _get_cfg(db, body.tenant_id, body.provider)
    if cfg is None:
        raise HTTPException(status_code=404, detail="SSO provider not found or not enabled")

    provider = body.provider
    client_id = cfg.client_id
    client_secret = cfg.client_secret
    registered_uri = (cfg.redirect_uri or "").strip()
    request_uri = (body.redirect_uri or "").strip()
    if not registered_uri:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "sso_redirect_uri_missing",
                "message": "租戶 SSO 尚未設定 redirect_uri",
            },
        )
    if request_uri != registered_uri:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "sso_redirect_uri_mismatch",
                "message": "redirect_uri 與租戶設定不符",
            },
        )
    redirect_uri = registered_uri
    if not client_id or not client_secret:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "sso_credentials_missing",
                "message": "Configure SSO client credentials in tenant SSO config",
            },
        )

    if provider == "google":
        token_url = "https://oauth2.googleapis.com/token"
    elif provider in ("microsoft", "azure"):
        import os

        ms_tenant = os.getenv("SSO_MS_TENANT", "common")
        token_url = f"https://login.microsoftonline.com/{ms_tenant}/oauth2/v2.0/token"
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported SSO provider: {provider}")

    data = {
        "grant_type": "authorization_code",
        "code": body.code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "client_secret": client_secret,
        "code_verifier": body.code_verifier,
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(token_url, data=data)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"token_exchange_failed: {exc}") from exc

    if resp.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail={"error": "token_exchange_rejected", "status": resp.status_code},
        )
    tokens = resp.json()

    # 5. 向 IdP 取已驗證 email
    email = _fetch_idp_email(provider, tokens)
    if not email:
        raise HTTPException(
            status_code=400,
            detail={"error": "idp_email_unavailable", "message": "IdP 未提供已驗證的 email"},
        )
    email = email.strip().lower()

    # 6. 網域白名單（fail-closed：有設清單就一定要命中）
    if cfg.allowed_domains:
        domain = email.rsplit("@", 1)[-1]
        if domain not in [d.lower() for d in cfg.allowed_domains]:
            raise HTTPException(status_code=403, detail="Email domain not allowed for this tenant")

    # 7. 帳號連結：只連結既有帳號；auto_create_user 開啟時才自動開戶
    user = crud_user.get_by_email(db, email=email)
    if user is None:
        if not cfg.auto_create_user:
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "sso_account_not_linked",
                    "message": "此 email 尚未開通 Enclave 帳號，請聯絡管理員",
                },
            )
        user = crud_user.create_sso_user(
            db,
            email=email,
            tenant_id=body.tenant_id,
            role=cfg.default_role or "employee",
        )

    # 8. 防跨租戶帳號連結：帳號必須屬於 state 指定的租戶
    if str(user.tenant_id) != str(body.tenant_id):
        raise HTTPException(status_code=403, detail="Account does not belong to this tenant")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Inactive user")

    # 9. 核發 Enclave JWT（含 MFA 閘門，與密碼登入一致——不可繞過 TOTP）
    from app.api.v1.endpoints.auth import build_login_response

    result = build_login_response(user)
    result["provider"] = provider
    return result


# ── 租戶 SSO 設定管理（owner/admin）─────────────────────────────

@router.get("/config", response_model=list[SSOConfigPublic])
def list_sso_configs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> list:
    """列出租戶 SSO 設定（不含 secret）。"""
    return (
        db.query(TenantSSOConfig)
        .filter(TenantSSOConfig.tenant_id == current_user.tenant_id)
        .all()
    )


@router.put("/config/{provider}", response_model=SSOConfigPublic)
def upsert_sso_config(
    provider: str,
    body: SSOConfigCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> TenantSSOConfig:
    """建立或更新租戶的 SSO 設定（僅 owner/admin）。"""
    if current_user.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Only owner/admin can configure SSO")
    if provider != body.provider:
        raise HTTPException(status_code=400, detail="provider mismatch")

    cfg = (
        db.query(TenantSSOConfig)
        .filter(
            TenantSSOConfig.tenant_id == current_user.tenant_id,
            TenantSSOConfig.provider == provider,
        )
        .first()
    )
    if cfg is None:
        cfg = TenantSSOConfig(tenant_id=current_user.tenant_id, provider=provider)
        db.add(cfg)
    cfg.client_id = body.client_id
    cfg.client_secret = body.client_secret
    cfg.redirect_uri = body.redirect_uri
    cfg.enabled = body.enabled
    cfg.allowed_domains = body.allowed_domains
    cfg.auto_create_user = body.auto_create_user
    cfg.default_role = body.default_role
    db.commit()
    db.refresh(cfg)
    return cfg
