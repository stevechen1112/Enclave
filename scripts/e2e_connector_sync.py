"""E2E: Connector create → sync → ACL projection → outbox event."""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))

env_path = root / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip()

os.environ.setdefault("POSTGRES_SERVER", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5435")
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("REDIS_PORT", "6380")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6380/0")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:6380/0")


def main() -> int:
    import httpx
    from sqlalchemy.orm import sessionmaker
    from app.db.session import engine
    from app.models.outbox import OutboxEvent
    from app.models.user import User
    from app.services.external_principal import ExternalPrincipalService

    base = "http://localhost:8000/api/v1"
    login = httpx.post(
        f"{base}/auth/login/access-token",
        data={
            "username": os.environ["E2E_ADMIN_EMAIL"],
            "password": os.environ["E2E_ADMIN_PASSWORD"],
        },
        timeout=30,
    )
    if login.status_code != 200:
        print(f"LOGIN FAIL {login.status_code} {login.text[:200]}")
        return 1
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    mock_resources = [
        {
            "source_record_id": "sp-file-enclave-001",
            "title": "SharePoint Quality Manual",
            "content_uri": "inline:text:Enclave connector slice — 品質管理手冊測試段落。",
            "mime_type": "text/plain",
            "metadata": {"source": "sharepoint", "path": "/sites/qa/manual.pdf"},
        },
    ]
    mock_acl = [
        {
            "provider": "sharepoint",
            "principal_external_id": "ext-user-qa-001",
            "source_record_id": "sp-file-enclave-001",
            "effect": "allow",
            "principal_type": "user",
        },
    ]

    body = {
        "connector_type": "sharepoint",
        "name": "E2E SharePoint Connector",
        "config": {
            "mock_resources": mock_resources,
            "mock_acl_entries": mock_acl,
            "site_url": "https://contoso.sharepoint.com/sites/qa",
            "allow_mock": True,
        },
    }
    created = httpx.post(f"{base}/connectors/", json=body, headers=headers, timeout=30)
    print(f"create connector: {created.status_code} {created.text[:300]}")
    if created.status_code not in (200, 201):
        return 1
    connector_id = created.json()["id"]

    synced = httpx.post(
        f"{base}/connectors/{connector_id}/sync",
        json={"full_reindex": False},
        headers=headers,
        timeout=120,
    )
    print(f"sync: {synced.status_code} {synced.text[:400]}")

    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        user = db.query(User).filter(User.email == "admin@example.com").first()
        tenant_id = user.tenant_id if user else None
        principal_svc = ExternalPrincipalService()
        acl_sample = principal_svc.sample_acl_for_source(
            db, tenant_id, "sp-file-enclave-001", limit=5,
        ) if tenant_id else []
        print(f"ACL projection rows: {len(acl_sample)}")
        events = (
            db.query(OutboxEvent)
            .filter(OutboxEvent.aggregate_type == "connector")
            .order_by(OutboxEvent.created_at.desc())
            .limit(3)
            .all()
        )
        print(f"recent outbox events: {[e.event_type for e in events]}")
    finally:
        db.close()

    pipeshub_url = os.getenv("PIPESHUB_BASE_URL", "http://localhost:8012")
    try:
        ph = httpx.get(f"{pipeshub_url}/api/v1/health/services", timeout=10)
        print(f"PipesHub health: {ph.status_code} {ph.text[:200]}")
    except Exception as exc:
        print(f"PipesHub health check skipped: {exc}")

    ok = synced.status_code == 200 and synced.json().get("status") == "completed"
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
