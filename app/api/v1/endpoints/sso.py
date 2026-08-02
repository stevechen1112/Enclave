"""SSO endpoints — state & PKCE helpers, OAuth callback skeleton."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.api.deps import get_db
from app.schemas.sso import (
    OAuthCallbackRequest,
    SSOStateRequest,
    SSOStateResponse,
)

router = APIRouter()


# ── Placeholder model reference until real TenantSSOConfig model is created ──
# When the real SQLAlchemy model is added, replace this import.
try:
    from app.models.tenant import TenantSSOConfig as _SSOModel
except ImportError:
    _SSOModel = None


# ── internal helpers ────────────────────────────────────────────

def _sign_state(payload: dict) -> str:
    """Create an HMAC-signed, base64url-encoded state token."""
    import base64

    data = json.dumps(payload, sort_keys=True).encode()
    sig = hmac.new(settings.SECRET_KEY.encode(), data, hashlib.sha256).hexdigest()
    token = base64.urlsafe_b64encode(data).decode() + "." + sig
    return token


def _verify_state(token: str) -> Optional[dict]:
    """Verify and decode a state token.  Returns None on failure."""
    import base64

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
        # check expiration
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None


# ── endpoints ───────────────────────────────────────────────────

def create_sso_state(
    body: SSOStateRequest,
    db: Session = Depends(get_db),
) -> SSOStateResponse:
    """Generate HMAC-signed state token for SSO login redirect.

    Verifies that the requested provider is enabled for the tenant
    before issuing a state token.
    """
    query_target = _SSOModel or object
    query = db.query(query_target)
    if _SSOModel is not None:
        query = query.filter(
            _SSOModel.tenant_id == str(body.tenant_id),
            _SSOModel.provider == body.provider,
            _SSOModel.enabled.is_(True),
        )

    cfg = query.first()

    if cfg is not None and _SSOModel is None:
        if str(getattr(cfg, "tenant_id", "")) != str(body.tenant_id):
            cfg = None
        elif getattr(cfg, "provider", None) != body.provider:
            cfg = None
        elif not bool(getattr(cfg, "enabled", False)):
            cfg = None

    if cfg is None:
        raise HTTPException(status_code=404, detail="SSO provider not found or not enabled")

    state_payload = {
        "tenant_id": str(body.tenant_id),
        "provider": body.provider,
        "exp": int(time.time()) + 600,  # 10 min
    }
    token = _sign_state(state_payload)
    return SSOStateResponse(state=token)


async def sso_callback(
    body: OAuthCallbackRequest,
    db: Session = Depends(get_db),
) -> dict:
    """Handle OAuth callback — verify state, exchange code for tokens.

    This is a skeleton: the actual token exchange with Google / Microsoft
    is not implemented yet.
    """
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

    # 4. Exchange authorization code (requires real client credentials in env / tenant SSO config)
    import os
    import httpx

    provider = body.provider
    client_id = os.getenv(f"SSO_{provider.upper()}_CLIENT_ID", "")
    client_secret = os.getenv(f"SSO_{provider.upper()}_CLIENT_SECRET", "")
    redirect_uri = body.redirect_uri or os.getenv(f"SSO_{provider.upper()}_REDIRECT_URI", "")
    try:
        cfg = (
            db.query(_SSOModel)
            .filter(
                _SSOModel.tenant_id == str(body.tenant_id),
                _SSOModel.provider == body.provider,
                _SSOModel.enabled.is_(True),
            )
            .first()
        ) if _SSOModel is not None else None
    except Exception:
        cfg = None
    if cfg is not None:
        client_id = getattr(cfg, "client_id", None) or client_id
        client_secret = getattr(cfg, "client_secret", None) or client_secret
        redirect_uri = body.redirect_uri or getattr(cfg, "redirect_uri", None) or redirect_uri

    if not client_id or not client_secret or not redirect_uri:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "sso_credentials_missing",
                "message": "Configure SSO client credentials or tenant SSO config",
            },
        )

    if provider == "google":
        token_url = "https://oauth2.googleapis.com/token"
    elif provider in ("microsoft", "azure", "sharepoint"):
        tenant = os.getenv("SSO_MS_TENANT", "common")
        token_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
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
        with httpx.Client(timeout=20.0) as client:
            resp = client.post(token_url, data=data)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"token_exchange_failed: {exc}") from exc

    if resp.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail={"error": "token_exchange_rejected", "status": resp.status_code, "body": resp.text[:500]},
        )
    tokens = resp.json()
    return {
        "status": "ok",
        "provider": provider,
        "token_type": tokens.get("token_type"),
        "expires_in": tokens.get("expires_in"),
        "scope": tokens.get("scope"),
        "has_access_token": bool(tokens.get("access_token")),
        "has_refresh_token": bool(tokens.get("refresh_token")),
        "has_id_token": bool(tokens.get("id_token")),
        # Do not echo secrets back
    }


# ── register routes ─────────────────────────────────────────────

router.add_api_route("/state", create_sso_state, methods=["POST"], response_model=SSOStateResponse)
router.add_api_route("/callback", sso_callback, methods=["POST"])
