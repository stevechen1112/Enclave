"""Connector config schemas (NAS / SharePoint / Google Drive) without requiring live OAuth."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ValidationError


class NasSmbConfig(BaseModel):
    root_path: str = Field(..., min_length=1)
    principal_external_id: str = "nas-local-reader"
    max_files: int = Field(default=200, ge=1, le=10000)
    include_globs: Optional[List[str]] = None


class SharePointConfig(BaseModel):
    site_url: str = Field(..., min_length=1, description="https://contoso.sharepoint.com/sites/docs")
    drive_id: Optional[str] = None
    library_name: Optional[str] = "Documents"
    tenant_id: Optional[str] = None
    client_id: Optional[str] = None
    # Secret stays in credential_ref / vault — never embed in config_json long-term
    credential_ref: Optional[str] = None
    scopes: List[str] = Field(default_factory=lambda: [
        "Sites.Read.All", "Files.Read.All", "offline_access",
    ])
    pipeshub_connector_name: str = "SHAREPOINT"


class GoogleDriveConfig(BaseModel):
    drive_id: Optional[str] = None  # My Drive if empty
    folder_id: Optional[str] = None
    client_id: Optional[str] = None
    credential_ref: Optional[str] = None
    scopes: List[str] = Field(default_factory=lambda: [
        "https://www.googleapis.com/auth/drive.readonly",
    ])
    pipeshub_connector_name: str = "DRIVE"


CONNECTOR_SCHEMAS = {
    "nas_smb": NasSmbConfig,
    "sharepoint": SharePointConfig,
    "google_drive": GoogleDriveConfig,
}


def validate_connector_config(connector_type: str, config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Validate and normalize connector config. Unknown GA types pass through lightly."""
    schema = CONNECTOR_SCHEMAS.get(connector_type)
    raw = config or {}
    if not schema:
        return dict(raw)
    try:
        return schema.model_validate(raw).model_dump(exclude_none=True)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc


def oauth_authorize_url(connector_type: str, config: Dict[str, Any], state: str, redirect_uri: str) -> Optional[str]:
    """Build authorize URL for OAuth connectors (token exchange still needs real client secret)."""
    if connector_type == "sharepoint":
        tenant = config.get("tenant_id") or "common"
        client_id = config.get("client_id") or ""
        if not client_id:
            return None
        scopes = " ".join(config.get("scopes") or [])
        return (
            f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"
            f"?client_id={client_id}&response_type=code&redirect_uri={redirect_uri}"
            f"&scope={scopes}&state={state}&response_mode=query"
        )
    if connector_type == "google_drive":
        client_id = config.get("client_id") or ""
        if not client_id:
            return None
        scopes = " ".join(config.get("scopes") or [])
        return (
            "https://accounts.google.com/o/oauth2/v2/auth"
            f"?client_id={client_id}&response_type=code&redirect_uri={redirect_uri}"
            f"&scope={scopes}&state={state}&access_type=offline&prompt=consent"
        )
    return None


def oauth_token_endpoint(connector_type: str, config: Dict[str, Any]) -> Optional[str]:
    if connector_type == "sharepoint":
        tenant = config.get("tenant_id") or "common"
        return f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    if connector_type == "google_drive":
        return "https://oauth2.googleapis.com/token"
    return None


def exchange_oauth_code(
    connector_type: str,
    *,
    code: str,
    redirect_uri: str,
    client_id: str,
    client_secret: str,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Exchange authorization code for tokens.
    Returns token payload; never logs secrets. Raises ValueError on failure.
    """
    import httpx

    cfg = config or {}
    token_url = oauth_token_endpoint(connector_type, cfg)
    if not token_url:
        raise ValueError(f"unsupported oauth connector_type={connector_type}")
    if not client_id or not client_secret:
        raise ValueError("client_id and client_secret required")
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    if connector_type == "sharepoint":
        scopes = cfg.get("scopes") or ["Sites.Read.All", "Files.Read.All", "offline_access"]
        data["scope"] = " ".join(scopes)
    with httpx.Client(timeout=20.0) as client:
        resp = client.post(token_url, data=data)
    if resp.status_code != 200:
        raise ValueError(f"token_exchange_rejected:{resp.status_code}:{resp.text[:300]}")
    tokens = resp.json()
    if not tokens.get("access_token"):
        raise ValueError("token_exchange_missing_access_token")
    return {
        "token_type": tokens.get("token_type"),
        "expires_in": tokens.get("expires_in"),
        "scope": tokens.get("scope"),
        "access_token": tokens.get("access_token"),
        "refresh_token": tokens.get("refresh_token"),
    }
