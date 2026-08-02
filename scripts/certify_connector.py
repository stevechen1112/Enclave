"""
Phase 3 — Connector certification suite.

- nas_smb：本機檔案掃描（無需雲端）
- sharepoint / google_drive：開發者測試 App（不是「客戶」憑證）
  從 .env 讀取 DEV_* / SHAREPOINT_* / GOOGLE_*；有憑證就跑 live 認證。

用法：
  python scripts/certify_connector.py --type all
  python scripts/certify_connector.py --type sharepoint
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ARTIFACT = ROOT / "artifacts" / "connector_cert_last_run.json"


def _load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def certify_nas_smb() -> dict:
    from app.services.nas_local_connector import scan_local_nas
    from app.services.connector_schemas import validate_connector_config

    checks = {}
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "a.txt").write_text("alpha doc", encoding="utf-8")
        (root / "b.txt").write_text("beta doc", encoding="utf-8")
        cfg = validate_connector_config("nas_smb", {"root_path": str(root), "max_files": 50})
        checks["schema"] = cfg["root_path"] == str(root)

        sync1 = scan_local_nas(str(root), max_files=50)
        checks["initial_sync"] = sync1.get("status") == "completed" and len(sync1.get("resources", [])) == 2
        checks["acl_present"] = len(sync1.get("acl_entries", [])) == 2

        (root / "a.txt").rename(root / "a_renamed.txt")
        sync2 = scan_local_nas(str(root), max_files=50)
        ids2 = {r["source_record_id"] for r in sync2.get("resources", [])}
        checks["rename_detected"] = "nas:a_renamed.txt" in ids2 and "nas:a.txt" not in ids2

        (root / "b.txt").unlink()
        sync3 = scan_local_nas(str(root), max_files=50)
        ids3 = {r["source_record_id"] for r in sync3.get("resources", [])}
        checks["delete_detected"] = "nas:b.txt" not in ids3 and len(ids3) == 1

        sync4 = scan_local_nas(str(root), max_files=50)
        hashes = sorted(r["content_hash"] for r in sync4.get("resources", []))
        hashes2 = sorted(r["content_hash"] for r in sync3.get("resources", []))
        checks["rescan_stable"] = hashes == hashes2

    checks["passed"] = all(checks.values())
    return {
        "connector_type": "nas_smb",
        "certified": bool(checks["passed"]),
        "checks": checks,
        "oauth_required": False,
        "mode": "local",
    }


def _env(*names: str) -> str:
    for n in names:
        v = (os.getenv(n) or "").strip()
        if v:
            return v
    return ""


def certify_sharepoint_dev() -> dict:
    """
    開發者 Azure App 認證（client_credentials）。
    需要：SHAREPOINT_CLIENT_ID + SHAREPOINT_CLIENT_SECRET + SHAREPOINT_TENANT_ID
    可選：SHAREPOINT_SITE_URL
    """
    import httpx
    from app.services.connector_schemas import validate_connector_config, oauth_authorize_url, oauth_token_endpoint

    client_id = _env("SHAREPOINT_CLIENT_ID", "DEV_SHAREPOINT_CLIENT_ID", "AZURE_CLIENT_ID")
    client_secret = _env("SHAREPOINT_CLIENT_SECRET", "DEV_SHAREPOINT_CLIENT_SECRET", "AZURE_CLIENT_SECRET")
    tenant_id = _env("SHAREPOINT_TENANT_ID", "DEV_SHAREPOINT_TENANT_ID", "AZURE_TENANT_ID") or "common"
    site_url = _env("SHAREPOINT_SITE_URL", "DEV_SHAREPOINT_SITE_URL") or "https://contoso.sharepoint.com/sites/dev"

    cfg = validate_connector_config(
        "sharepoint",
        {"site_url": site_url, "client_id": client_id or "pending", "tenant_id": tenant_id},
    )
    auth_url = oauth_authorize_url("sharepoint", {**cfg, "client_id": client_id or "pending"}, "dev", "http://localhost:8000/oauth/callback")
    base = {
        "connector_type": "sharepoint",
        "oauth_required": True,
        "mode": "developer_app",
        "schema_ok": True,
        "authorize_url_ok": bool(auth_url),
        "note": "Uses developer Azure app (not customer tenant)",
    }
    if not client_id or not client_secret or tenant_id == "common":
        return {
            **base,
            "certified": False,
            "missing_env": [
                k for k, v in [
                    ("SHAREPOINT_CLIENT_ID", client_id),
                    ("SHAREPOINT_CLIENT_SECRET", client_secret),
                    ("SHAREPOINT_TENANT_ID", None if tenant_id == "common" else tenant_id),
                ] if not v
            ],
            "setup": "docs/runbooks/DEV_OAUTH_SETUP.md",
        }

    token_url = oauth_token_endpoint("sharepoint", {"tenant_id": tenant_id})
    assert token_url
    checks = {"schema": True, "authorize_url": bool(auth_url), "token": False, "graph": False}
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "scope": "https://graph.microsoft.com/.default",
                },
            )
            checks["token"] = resp.status_code == 200 and bool(resp.json().get("access_token"))
            if not checks["token"]:
                return {
                    **base,
                    "certified": False,
                    "checks": checks,
                    "error": f"token_http_{resp.status_code}:{resp.text[:200]}",
                }
            token = resp.json()["access_token"]
            # 輕量 Graph 探測（不要求特定 site 一定存在）
            g = client.get(
                "https://graph.microsoft.com/v1.0/sites?search=*",
                headers={"Authorization": f"Bearer {token}"},
            )
            checks["graph"] = g.status_code in (200, 400, 403)  # 403 仍證明 token 被 Graph 接受但權限不足
            if g.status_code == 401:
                checks["graph"] = False
    except Exception as exc:
        return {**base, "certified": False, "checks": checks, "error": str(exc)[:300]}

    certified = checks["token"] and checks["graph"]
    return {
        **base,
        "certified": certified,
        "checks": checks,
        "tenant_id": tenant_id,
    }


def certify_google_drive_dev() -> dict:
    """
    開發者 Google OAuth 客戶端認證。
    完整 live：GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET + GOOGLE_REFRESH_TOKEN
    （refresh_token 由開發者本機瀏覽器同意一次後寫入 .env）
    """
    import httpx
    from app.services.connector_schemas import validate_connector_config, oauth_authorize_url

    client_id = _env("GOOGLE_CLIENT_ID", "DEV_GOOGLE_CLIENT_ID")
    client_secret = _env("GOOGLE_CLIENT_SECRET", "DEV_GOOGLE_CLIENT_SECRET")
    refresh_token = _env("GOOGLE_REFRESH_TOKEN", "DEV_GOOGLE_REFRESH_TOKEN")

    cfg = validate_connector_config("google_drive", {"client_id": client_id or "pending"})
    auth_url = oauth_authorize_url(
        "google_drive", {**cfg, "client_id": client_id or "pending"}, "dev",
        "http://localhost:8000/oauth/callback",
    )
    base = {
        "connector_type": "google_drive",
        "oauth_required": True,
        "mode": "developer_app",
        "schema_ok": True,
        "authorize_url_ok": bool(auth_url),
        "note": "Uses developer Google Cloud OAuth client (not customer)",
    }
    if not client_id or not client_secret:
        return {
            **base,
            "certified": False,
            "missing_env": [k for k, v in [
                ("GOOGLE_CLIENT_ID", client_id),
                ("GOOGLE_CLIENT_SECRET", client_secret),
            ] if not v],
            "setup": "docs/runbooks/DEV_OAUTH_SETUP.md",
        }

    checks = {
        "schema": True,
        "authorize_url": bool(auth_url),
        "client_accepted": False,
        "refresh": False,
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            # 用不合法 code 探測 client_id/secret 是否被 Google 接受（預期 invalid_grant）
            probe = client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "grant_type": "authorization_code",
                    "code": "enclave-dev-probe-invalid",
                    "redirect_uri": "http://localhost:8000/oauth/callback",
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
            )
            body = {}
            try:
                body = probe.json()
            except Exception:
                pass
            err = str(body.get("error") or "")
            # invalid_client = 憑證錯；invalid_grant = client 有效但 code 無效（期望）
            checks["client_accepted"] = err in ("invalid_grant", "invalid_request") or probe.status_code == 200
            if err == "invalid_client":
                return {
                    **base,
                    "certified": False,
                    "checks": checks,
                    "error": "invalid_client — check GOOGLE_CLIENT_ID/SECRET",
                }

            if refresh_token:
                ref = client.post(
                    "https://oauth2.googleapis.com/token",
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token,
                        "client_id": client_id,
                        "client_secret": client_secret,
                    },
                )
                checks["refresh"] = ref.status_code == 200 and bool(ref.json().get("access_token"))
                if checks["refresh"]:
                    # Drive API 探測
                    token = ref.json()["access_token"]
                    d = client.get(
                        "https://www.googleapis.com/drive/v3/files",
                        headers={"Authorization": f"Bearer {token}"},
                        params={"pageSize": 1},
                    )
                    checks["drive_api"] = d.status_code == 200
                certified = checks["client_accepted"] and checks["refresh"] and checks.get("drive_api")
            else:
                # 僅 client 有效仍不算完整認證
                certified = False
                base["missing_env"] = ["GOOGLE_REFRESH_TOKEN"]
                base["setup"] = "docs/runbooks/DEV_OAUTH_SETUP.md"
    except Exception as exc:
        return {**base, "certified": False, "checks": checks, "error": str(exc)[:300]}

    return {**base, "certified": bool(certified), "checks": checks}


def main() -> int:
    _load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--type", default="all", choices=["nas_smb", "sharepoint", "google_drive", "all"])
    args = p.parse_args()

    results = []
    if args.type in ("nas_smb", "all"):
        results.append(certify_nas_smb())
    if args.type in ("sharepoint", "all"):
        results.append(certify_sharepoint_dev())
    if args.type in ("google_drive", "all"):
        results.append(certify_google_drive_dev())

    nas = next((r for r in results if r.get("connector_type") == "nas_smb"), None)
    # 套件 PASS 最低門檻仍是 NAS；oauth 結果如實寫入
    status = "PASS" if nas and nas.get("certified") else "FAIL"
    oauth_certified = [
        r["connector_type"] for r in results
        if r.get("connector_type") != "nas_smb" and r.get("certified")
    ]
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "results": results,
        "oauth_certified": oauth_certified,
        "note": "OAuth connectors use developer test apps from .env (not customer credentials)",
    }
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
