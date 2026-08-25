from datetime import timedelta
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api import deps
from app.config import settings
from app.core import security
from app.core.security import (
    SCOPE_MFA_ENROLL,
    SCOPE_MFA_PENDING,
)
from app.crud import crud_user
from app.demo.manifest import DEMO_PERSONAS
from app.models.tenant import Tenant
from app.models.user import User
from app.services import totp
from app.services.emailer import (
    parse_verification_token,
    send_verification_email,
)

router = APIRouter()


DemoPersona = Literal["sales", "field", "master", "newcomer", "viewer", "admin"]

class DemoLoginRequest(BaseModel):
    persona: DemoPersona


def _resolve_demo_user(db: Session, persona: DemoPersona) -> tuple[User, dict[str, Any]]:
    """Resolve an allowlisted demo identity and fail closed on configuration drift."""
    from app.models.mka import JobRole, UserJobRoleAssignment
    from app.services.rls import apply_rls_bypass

    spec = DEMO_PERSONAS[persona]
    apply_rls_bypass(db)
    try:
        demo_tenant_id = UUID(settings.DEMO_TENANT_ID)
    except (TypeError, ValueError, AttributeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Demo tenant is not configured",
        ) from exc
    tenant = db.query(Tenant).filter(
        Tenant.id == demo_tenant_id,
        Tenant.is_demo.is_(True),
        Tenant.status == "active",
    ).first()
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Demo tenant is not available",
        )

    preferred_email = settings.DEMO_ADMIN_EMAIL if persona == "admin" else spec["email"]
    user = db.query(User).filter(
        User.email == preferred_email,
        User.tenant_id == tenant.id,
    ).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Demo role is not available",
        )
    if user.role != spec["security_role"]:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Demo role configuration mismatch",
        )
    # Company management is tenant ownership, never platform superuser access.
    if user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Demo role configuration mismatch",
        )

    expected_job_role = spec.get("job_role")
    if expected_job_role:
        assignment = (
            db.query(UserJobRoleAssignment)
            .join(JobRole, JobRole.id == UserJobRoleAssignment.job_role_id)
            .filter(
                UserJobRoleAssignment.user_id == user.id,
                UserJobRoleAssignment.tenant_id == user.tenant_id,
                UserJobRoleAssignment.active.is_(True),
                JobRole.role_key == expected_job_role,
                JobRole.active.is_(True),
            )
            .first()
        )
        if assignment is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Demo job role is not assigned",
            )
    return user, spec


@router.post("/login/demo")
def demo_login(body: DemoLoginRequest, db: Session = Depends(deps.get_db)) -> dict[str, Any]:
    """Issue a short-lived token for one of the explicitly allowlisted demo doors."""
    if not settings.DEMO_LOGIN_ENABLED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    user, spec = _resolve_demo_user(db, body.persona)
    expires = timedelta(minutes=settings.DEMO_ACCESS_TOKEN_EXPIRE_MINUTES)
    return {
        "access_token": security.create_access_token(
            user.email,
            expires_delta=expires,
            tenant_id=user.tenant_id,
            additional_claims={
                "demo_mode": True,
                "demo_persona": body.persona,
                "demo_read_only": bool(spec["read_only"]),
                "demo_mutation_scope": spec["mutation_scope"],
            },
        ),
        "token_type": "bearer",
        "persona": body.persona,
        "read_only": bool(spec["read_only"]),
        "expires_in": int(expires.total_seconds()),
    }


def _issue_full_token(user: User) -> dict:
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return {
        "access_token": security.create_access_token(
            user.email,
            expires_delta=access_token_expires,
            tenant_id=user.tenant_id,
        ),
        "token_type": "bearer",
    }


def build_login_response(user: User) -> dict:
    """密碼登入與 SSO callback 共用的 MFA 閘門（CG-AUTH-SSO）。"""
    if user.mfa_enabled:
        return {
            "mfa_required": True,
            "partial_token": security.create_partial_token(
                user.email, scope=SCOPE_MFA_PENDING, tenant_id=user.tenant_id
            ),
            "token_type": "mfa_partial",
        }
    if settings.MFA_ENFORCE_OWNER and user.role == "owner":
        return {
            "mfa_enroll_required": True,
            "partial_token": security.create_partial_token(
                user.email, scope=SCOPE_MFA_ENROLL, tenant_id=user.tenant_id
            ),
            "token_type": "mfa_partial",
        }
    return _issue_full_token(user)


@router.post("/login/access-token")
def login_access_token(
    db: Session = Depends(deps.get_db), form_data: OAuth2PasswordRequestForm = Depends()
) -> Any:
    """
    OAuth2 compatible token login, get an access token for future requests

    CG-AUTH-SSO：MFA 流程——
    - 已啟用 MFA：回 200 + mfa_required + partial_token（scope=mfa_pending，不可呼叫其他 API）
    - MFA_ENFORCE_OWNER 且 owner 未設定 MFA：回 mfa_enroll_required + partial_token（scope=mfa_enroll）
    """
    # ADR-012：users 表在 RLS 下受租戶 policy 約束；登入時尚無租戶 context，
    # email 查找必須走平台維運 bypass 通道，否則 enforce 階段登入完全失效。
    from app.services.rls import apply_rls_bypass

    apply_rls_bypass(db)
    user = crud_user.authenticate(
        db, email=form_data.username, password=form_data.password
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    elif not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user"
        )

    return build_login_response(user)


# ── MFA（TOTP）───────────────────────────────────────────────


class MFACodeRequest(BaseModel):
    code: str


class MFAVerifyRequest(BaseModel):
    partial_token: str
    code: str


class MFASetupResponse(BaseModel):
    secret: str
    provisioning_uri: str


def _user_from_partial(db: Session, partial_token: str, allowed_scopes: tuple[str, ...]) -> User:
    payload = security.decode_partial_token(partial_token)
    if not payload or payload.get("scope") not in allowed_scopes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid or expired partial token"
        )
    from app.services.rls import apply_rls_bypass

    apply_rls_bypass(db)
    user = crud_user.get_by_email(db, email=payload.get("sub", ""))
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


@router.post("/mfa/setup", response_model=MFASetupResponse)
def mfa_setup(
    db: Session = Depends(deps.get_db),
    partial_token: str | None = None,
    current_user: User | None = Depends(deps.get_current_user_optional),
) -> Any:
    """產生 TOTP secret（尚未啟用，需 /mfa/enable 確認）。

    接受兩種身分：完整 token（已登入用戶自願開通）或 mfa_enroll 局部 token（強制開通流程）。
    """
    if current_user is not None:
        user = current_user
    elif partial_token:
        user = _user_from_partial(db, partial_token, (SCOPE_MFA_ENROLL,))
    else:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    if user.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA already enabled")

    secret = totp.generate_secret()
    user.mfa_secret = secret
    db.add(user)
    db.commit()
    return MFASetupResponse(
        secret=secret,
        provisioning_uri=totp.provisioning_uri(secret, email=user.email),
    )


@router.post("/mfa/enable")
def mfa_enable(
    body: MFACodeRequest,
    db: Session = Depends(deps.get_db),
    partial_token: str | None = None,
    current_user: User | None = Depends(deps.get_current_user_optional),
) -> Any:
    """以 TOTP 碼確認並啟用 MFA。mfa_enroll 流程成功後直接核發完整 token。"""
    enroll_user: User | None = None
    if current_user is not None:
        user = current_user
    elif partial_token:
        enroll_user = _user_from_partial(db, partial_token, (SCOPE_MFA_ENROLL,))
        user = enroll_user
    else:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    if not user.mfa_secret:
        raise HTTPException(status_code=400, detail="Call /mfa/setup first")
    if not totp.verify(user.mfa_secret, body.code):
        raise HTTPException(status_code=400, detail="Invalid TOTP code")

    user.mfa_enabled = True
    db.add(user)
    db.commit()

    # 強制開通流程：啟用完成即核發完整 token，無需再登入一次
    if enroll_user is not None:
        return _issue_full_token(enroll_user)
    return {"status": "ok", "mfa_enabled": True}


@router.post("/mfa/verify")
def mfa_verify(body: MFAVerifyRequest, db: Session = Depends(deps.get_db)) -> Any:
    """MFA 第二階段：partial_token + TOTP 碼 → 完整 access token。"""
    user = _user_from_partial(db, body.partial_token, (SCOPE_MFA_PENDING,))
    if not user.mfa_enabled or not user.mfa_secret:
        raise HTTPException(status_code=400, detail="MFA not enabled")
    if not totp.verify(user.mfa_secret, body.code):
        raise HTTPException(status_code=400, detail="Invalid TOTP code")
    return _issue_full_token(user)


@router.post("/mfa/disable")
def mfa_disable(
    body: MFACodeRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """停用 MFA（需完整 token＋有效 TOTP 碼，防止被劫持後直接關閉）。"""
    if not current_user.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA not enabled")
    if settings.MFA_ENFORCE_OWNER and current_user.role == "owner":
        raise HTTPException(status_code=403, detail="Owner MFA is enforced by policy")
    if not totp.verify(current_user.mfa_secret or "", body.code):
        raise HTTPException(status_code=400, detail="Invalid TOTP code")
    current_user.mfa_enabled = False
    current_user.mfa_secret = None
    db.add(current_user)
    db.commit()
    return {"status": "ok", "mfa_enabled": False}


# ── Email 驗證 ───────────────────────────────────────────────


class VerifyEmailRequest(BaseModel):
    token: str


@router.post("/verify-email")
def verify_email(body: VerifyEmailRequest, db: Session = Depends(deps.get_db)) -> Any:
    """以 email 連結中的 token 完成驗證。"""
    email = parse_verification_token(body.token)
    if not email:
        raise HTTPException(status_code=400, detail="Invalid or expired verification token")

    from app.services.rls import apply_rls_bypass

    apply_rls_bypass(db)
    user = crud_user.get_by_email(db, email=email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.email_verified = True
    db.add(user)
    db.commit()
    return {"status": "ok", "email_verified": True}


@router.post("/resend-verification")
def resend_verification(
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """重寄驗證信（需登入）。回傳 delivered 表示是否真的經 SMTP 寄出。"""
    if current_user.email_verified:
        return {"status": "ok", "email_verified": True, "delivered": False}
    delivered = send_verification_email(current_user.email)
    return {"status": "ok", "delivered": delivered}
