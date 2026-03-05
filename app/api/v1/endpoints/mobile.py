"""
Phase 12 — Mobile App Backend Endpoints

Provides APIs consumed exclusively by the mobile client:
  - POST /auth/refresh-token    → issue a new JWT from a valid (not-yet-expired) token
  - POST /auth/revoke-token     → blacklist current JWT (logout invalidation)
  - POST /users/me/push-token   → register Expo push token for notifications
  - DELETE /users/me/push-token → unregister push token on logout
  - POST /security/events       → report security events from mobile client
  - GET  /security/cert-fingerprint → return server TLS cert SHA-256 for pinning
"""
import hashlib
import ssl
import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from jose import jwt
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api import deps
from app.config import settings
from app.core import security
from app.models.audit import AuditLog
from app.models.user import User

router = APIRouter()


# ─── Schemas ────────────────────────────────────────────────────────────────────

class PushTokenIn(BaseModel):
    push_token: str  # Expo push token, e.g. "ExponentPushToken[...]"
    device_platform: Optional[str] = None  # "ios" | "android"


class SecurityEventIn(BaseModel):
    event_type: str  # e.g. "cert_mismatch", "jailbreak_detected"
    detail: Optional[dict] = None


class CertFingerprintOut(BaseModel):
    sha256: str
    issued_to: Optional[str] = None


# ─── Token Refresh ──────────────────────────────────────────────────────────────

@router.post("/auth/refresh-token", response_model=dict)
def refresh_token(
    request: Request,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Issue a new JWT if the caller's current token is still valid.
    The old token remains valid until it naturally expires (stateless JWT).
    """
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    new_token = security.create_access_token(
        current_user.email, expires_delta=access_token_expires
    )
    return {"access_token": new_token, "token_type": "bearer"}


# ─── Token Revocation (best-effort audit log) ──────────────────────────────────

@router.post("/auth/revoke-token", status_code=204)
def revoke_token(
    request: Request,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Mark the current session as logged-out.
    Since we use stateless JWTs, this records a logout audit entry.
    For full revocation, integrate a token blacklist (Redis) in production.
    """
    audit = AuditLog(
        tenant_id=current_user.tenant_id,
        actor_user_id=current_user.id,
        action="logout",
        target_type="user",
        target_id=str(current_user.id),
        ip_address=request.client.host if request.client else None,
        detail_json={"source": "mobile", "method": "revoke_token"},
    )
    db.add(audit)
    db.commit()
    return None


# ─── Push Token Management ──────────────────────────────────────────────────────

@router.post("/users/me/push-token", status_code=204)
def register_push_token(
    body: PushTokenIn,
    request: Request,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Register an Expo push notification token for the current user.
    Stores via audit log for now; production should use a dedicated PushToken table.
    """
    audit = AuditLog(
        tenant_id=current_user.tenant_id,
        actor_user_id=current_user.id,
        action="push_token_register",
        target_type="device",
        target_id=body.push_token[:80],
        ip_address=request.client.host if request.client else None,
        detail_json={
            "push_token": body.push_token,
            "platform": body.device_platform,
            "source": "mobile",
        },
    )
    db.add(audit)
    db.commit()
    return None


@router.delete("/users/me/push-token", status_code=204)
def unregister_push_token(
    request: Request,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Unregister push token on logout / app uninstall.
    """
    audit = AuditLog(
        tenant_id=current_user.tenant_id,
        actor_user_id=current_user.id,
        action="push_token_unregister",
        target_type="device",
        ip_address=request.client.host if request.client else None,
        detail_json={"source": "mobile"},
    )
    db.add(audit)
    db.commit()
    return None


# ─── Security Events ────────────────────────────────────────────────────────────

@router.post("/security/events", status_code=204)
def report_security_event(
    body: SecurityEventIn,
    request: Request,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Mobile client reports a security event (cert mismatch, jailbreak, etc.).
    Persisted to AuditLog for SOC review.
    """
    audit = AuditLog(
        tenant_id=current_user.tenant_id,
        actor_user_id=current_user.id,
        action=f"security_event:{body.event_type}",
        target_type="security",
        ip_address=request.client.host if request.client else None,
        detail_json={
            "event_type": body.event_type,
            **(body.detail or {}),
            "source": "mobile",
        },
    )
    db.add(audit)
    db.commit()
    return None


# ─── Certificate Fingerprint ────────────────────────────────────────────────────

@router.get("/security/cert-fingerprint", response_model=CertFingerprintOut)
def get_cert_fingerprint():
    """
    Return the SHA-256 fingerprint of the server's TLS certificate.
    Mobile clients compare this against the pinned fingerprint to detect MITM.

    Falls back to a placeholder when running without TLS (dev / behind reverse proxy).
    """
    try:
        # In production, the TLS cert is typically terminated at the reverse proxy.
        # For self-signed / direct TLS setups, read the cert file.
        import os

        cert_path = os.environ.get("TLS_CERT_PATH", "/etc/ssl/certs/server.crt")
        if os.path.exists(cert_path):
            with open(cert_path, "rb") as f:
                cert_der = ssl.PEM_cert_to_DER_cert(f.read().decode())
            sha256 = hashlib.sha256(cert_der).hexdigest()
            return CertFingerprintOut(sha256=sha256, issued_to=cert_path)

        # Fallback: return a config-driven fingerprint if set
        env_fingerprint = os.environ.get("TLS_CERT_SHA256", "")
        if env_fingerprint:
            return CertFingerprintOut(sha256=env_fingerprint, issued_to="env")

        return CertFingerprintOut(
            sha256="development-no-tls",
            issued_to="localhost (no TLS)",
        )
    except Exception:
        return CertFingerprintOut(sha256="unavailable", issued_to=None)
