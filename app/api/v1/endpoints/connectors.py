"""Phase 3 — Connector management API."""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api import deps
from app.api.deps_permissions import require_admin
from app.models.user import User
from app.services.connector_manager import GA_CONNECTORS, ConnectorManager
from app.services.connector_sync import ConnectorSyncService
from app.services.module_gate import require_module
from app.services.product_license import ProductModule


def _require_connect_pack() -> None:
    require_module(ProductModule.ENTERPRISE_CONNECT)

router = APIRouter(prefix="/connectors", tags=["connectors"])
_manager = ConnectorManager()
_sync = ConnectorSyncService()


class ConnectorCreate(BaseModel):
    connector_type: str = Field(..., description="nas_smb | sharepoint | google_drive | ...")
    name: str
    config: Optional[Dict[str, Any]] = None


class CredentialRotate(BaseModel):
    credential_ref: str = Field(..., min_length=1)


class ConnectorOut(BaseModel):
    id: str
    connector_type: str
    name: str
    status: str
    last_sync_at: Optional[str] = None
    last_error: Optional[str] = None


@router.get("/types")
def list_connector_types(current_user: User = Depends(require_admin)) -> Dict[str, Any]:
    from app.services.connector_schemas import CONNECTOR_SCHEMAS
    return {
        "ga_connectors": GA_CONNECTORS,
        "certified_local": ["nas_smb"],
        "oauth_ready_schema": ["sharepoint", "google_drive"],
        "schemas": {k: list(v.model_fields.keys()) for k, v in CONNECTOR_SCHEMAS.items()},
        "all_certified": ["nas_smb"],  # honest: only NAS local certified without OAuth
    }


class OAuthStartRequest(BaseModel):
    connector_type: str
    config: Dict[str, Any] = Field(default_factory=dict)
    redirect_uri: str = Field(..., min_length=1)
    state: Optional[str] = None


@router.post("/oauth/authorize-url")
def oauth_authorize_url(
    body: OAuthStartRequest,
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Build OAuth authorize URL for SharePoint / Google Drive."""
    _require_connect_pack()
    from app.services.connector_schemas import (
        oauth_authorize_url,
        validate_connector_config,
    )
    try:
        cfg = validate_connector_config(body.connector_type, body.config)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    state = body.state or f"{current_user.tenant_id}:{body.connector_type}"
    url = oauth_authorize_url(body.connector_type, cfg, state, body.redirect_uri)
    if not url:
        raise HTTPException(
            status_code=400,
            detail="client_id required in config to build authorize URL",
        )
    return {
        "authorize_url": url,
        "state": state,
        "connector_type": body.connector_type,
        "next": "POST /connectors/oauth/token-exchange with code + client_secret",
    }


class OAuthTokenExchangeRequest(BaseModel):
    connector_type: str
    code: str = Field(..., min_length=1)
    redirect_uri: str = Field(..., min_length=1)
    client_id: str = Field(..., min_length=1)
    client_secret: str = Field(..., min_length=1)
    config: Dict[str, Any] = Field(default_factory=dict)
    connector_id: Optional[UUID] = None
    store_credential_ref: bool = True


@router.post("/oauth/token-exchange")
def oauth_token_exchange(
    body: OAuthTokenExchangeRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """
    Exchange OAuth code for tokens and optionally bind credential_ref to a connector.
    Access/refresh tokens are NOT returned in full — only a credential_ref handle.
    """
    _require_connect_pack()
    import hashlib

    from app.services.connector_schemas import (
        exchange_oauth_code,
        validate_connector_config,
    )

    try:
        cfg = validate_connector_config(body.connector_type, body.config)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        tokens = exchange_oauth_code(
            body.connector_type,
            code=body.code,
            redirect_uri=body.redirect_uri,
            client_id=body.client_id,
            client_secret=body.client_secret,
            config=cfg,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Store token material outside uploads/ (DD-M14) — Fernet-sealed at rest
    from app.services.credential_vault import (
        ensure_credential_dir,
        write_credential_file,
    )

    vault_dir = ensure_credential_dir()
    digest = hashlib.sha256(
        f"{current_user.tenant_id}:{body.connector_type}:{tokens.get('access_token', '')[:32]}".encode()
    ).hexdigest()[:24]
    credential_ref = f"cred:{body.connector_type}:{digest}"
    secret_path = vault_dir / f"{digest}.bin"
    write_credential_file(
        secret_path,
        {
            "connector_type": body.connector_type,
            "token_type": tokens.get("token_type"),
            "expires_in": tokens.get("expires_in"),
            "scope": tokens.get("scope"),
            "access_token": tokens.get("access_token"),
            "refresh_token": tokens.get("refresh_token"),
            "tenant_id": str(current_user.tenant_id),
        },
    )

    bound = False
    if body.store_credential_ref and body.connector_id:
        from app.models.connector import ConnectorInstance
        row = db.query(ConnectorInstance).filter(
            ConnectorInstance.id == body.connector_id,
            ConnectorInstance.tenant_id == current_user.tenant_id,
        ).first()
        if not row:
            raise HTTPException(status_code=404, detail="連接器不存在")
        _sync.rotate_credential_ref(db, body.connector_id, credential_ref)
        cfg2 = dict(row.config_json or {})
        cfg2["credential_ref"] = credential_ref
        cfg2["client_id"] = body.client_id
        row.config_json = cfg2
        db.commit()
        bound = True

    return {
        "status": "ok",
        "connector_type": body.connector_type,
        "credential_ref": credential_ref,
        "expires_in": tokens.get("expires_in"),
        "has_refresh_token": bool(tokens.get("refresh_token")),
        "bound_to_connector": bound,
        "note": "Tokens stored server-side; use credential_ref only",
    }


@router.get("/", response_model=List[ConnectorOut])
def list_connectors(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_admin),
) -> Any:
    rows = _manager.list_connectors(db, current_user.tenant_id)
    return [
        ConnectorOut(
            id=str(r.id),
            connector_type=r.connector_type,
            name=r.name,
            status=r.status,
            last_sync_at=r.last_sync_at.isoformat() if r.last_sync_at else None,
            last_error=r.last_error,
        )
        for r in rows
    ]


@router.post("/", response_model=ConnectorOut)
def create_connector(
    body: ConnectorCreate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_admin),
) -> Any:
    _require_connect_pack()
    try:
        row = _manager.create_connector(
            db, current_user.tenant_id, body.connector_type, body.name, body.config,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ConnectorOut(
        id=str(row.id), connector_type=row.connector_type,
        name=row.name, status=row.status,
    )


@router.post("/{connector_id}/pause")
def pause_connector(
    connector_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    _require_connect_pack()
    from app.models.connector import ConnectorInstance
    existing = db.query(ConnectorInstance).filter(ConnectorInstance.id == connector_id).first()
    if not existing or existing.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="連接器不存在")
    row = _manager.pause(db, connector_id)
    if not row:
        raise HTTPException(status_code=404, detail="連接器不存在")
    return {"status": row.status}


@router.post("/{connector_id}/resume")
def resume_connector(
    connector_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    _require_connect_pack()
    from app.models.connector import ConnectorInstance
    existing = db.query(ConnectorInstance).filter(ConnectorInstance.id == connector_id).first()
    if not existing or existing.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="連接器不存在")
    row = _manager.resume(db, connector_id)
    if not row:
        raise HTTPException(status_code=404, detail="連接器不存在")
    return {"status": row.status}


@router.get("/{connector_id}/status")
def connector_status(
    connector_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    from app.models.connector import ConnectorInstance, ConnectorResource
    row = db.query(ConnectorInstance).filter(ConnectorInstance.id == connector_id).first()
    if not row or row.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="連接器不存在")
    resource_count = (
        db.query(ConnectorResource)
        .filter(ConnectorResource.connector_instance_id == connector_id)
        .count()
    )
    return {
        "id": str(row.id),
        "status": row.status,
        "last_sync_at": row.last_sync_at.isoformat() if row.last_sync_at else None,
        "last_error": row.last_error,
        "resource_count": resource_count,
        "sync_state": row.sync_state or {},
        "lag_seconds": (
            int((__import__("datetime").datetime.now(__import__("datetime").timezone.utc) - row.last_sync_at).total_seconds())
            if row.last_sync_at else None
        ),
        "credential_ref_set": bool(row.credential_ref),
    }


@router.post("/{connector_id}/sync")
def trigger_sync(
    connector_id: UUID,
    full_reindex: bool = False,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    _require_connect_pack()
    from app.models.connector import ConnectorInstance
    row = db.query(ConnectorInstance).filter(ConnectorInstance.id == connector_id).first()
    if not row or row.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="連接器不存在")
    # This endpoint is the sole executor for an interactive sync. Publishing a
    # sync_requested event before running synchronously lets the outbox worker
    # execute the same connector concurrently. run_sync emits sync_completed.
    return _sync.run_sync(
        db, connector_id, full_reindex=full_reindex, uploaded_by=current_user.id,
    )


@router.post("/{connector_id}/reindex")
def reindex_connector(
    connector_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    return trigger_sync(connector_id, full_reindex=True, db=db, current_user=current_user)


@router.post("/{connector_id}/credentials/rotate")
def rotate_credentials(
    connector_id: UUID,
    body: CredentialRotate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    _require_connect_pack()
    from app.models.connector import ConnectorInstance
    row = db.query(ConnectorInstance).filter(ConnectorInstance.id == connector_id).first()
    if not row or row.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="連接器不存在")
    updated = _sync.rotate_credential_ref(db, connector_id, body.credential_ref)
    if not updated:
        raise HTTPException(status_code=404, detail="連接器不存在")
    return {"status": "rotated", "credential_ref": updated.credential_ref}


@router.delete("/{connector_id}")
def delete_connector(
    connector_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    _require_connect_pack()
    from app.models.connector import ConnectorInstance
    row = db.query(ConnectorInstance).filter(ConnectorInstance.id == connector_id).first()
    if not row or row.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="連接器不存在")
    ok = _sync.delete_connector(db, connector_id)
    return {"status": "deleted" if ok else "error"}


@router.get("/acl/sample/{source_record_id}")
def sample_source_acl(
    source_record_id: str,
    limit: int = 20,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    entries = _sync.sample_acl(db, current_user.tenant_id, source_record_id, limit=limit)
    return {"source_record_id": source_record_id, "entries": entries, "count": len(entries)}
