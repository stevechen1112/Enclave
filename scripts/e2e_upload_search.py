"""E2E: login → upload → process → gateway search (local Enclave API)."""
from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

BASE = os.getenv("E2E_API_BASE", "http://localhost:8000/api/v1")
EMAIL = os.getenv("E2E_ADMIN_EMAIL", "admin@example.com")
PASSWORD = os.getenv("E2E_ADMIN_PASSWORD", os.getenv("FIRST_SUPERUSER_PASSWORD", "admin123"))
SAMPLE = ROOT / "tests" / "fixtures" / "sample.txt"


def main() -> int:
    print("=== Enclave E2E: upload → index → gateway search ===\n")
    client = httpx.Client(base_url=BASE, timeout=120.0)

    # Health
    try:
        h = client.get("/health")
        print(f"API health: {h.status_code}")
    except Exception as exc:
        print(f"API not reachable at {BASE}: {exc}")
        print("Start: uvicorn app.main:app --host 0.0.0.0 --port 8000")
        return 1

    # Login
    login = client.post(
        "/auth/login/access-token",
        data={"username": EMAIL, "password": PASSWORD},
    )
    if login.status_code != 200:
        print(f"Login failed: {login.status_code} {login.text[:300]}")
        return 1
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    print(f"Login OK: {EMAIL}")

    # Upload
    if not SAMPLE.exists():
        SAMPLE.write_text(
            "Enclave E2E integration test.\n製造業品質管理：檢驗流程與不良品處理規範。",
            encoding="utf-8",
        )
    with SAMPLE.open("rb") as f:
        up = client.post(
            "/documents/upload",
            headers=headers,
            files={"file": ("e2e-sample.txt", f, "text/plain")},
        )
    if up.status_code not in (200, 201):
        print(f"Upload failed: {up.status_code} {up.text[:400]}")
        return 1
    doc = up.json()
    doc_id = doc.get("id")
    print(f"Upload OK: document_id={doc_id} status={doc.get('status')}")

    # Poll document status (Celery worker must be running)
    completed = False
    for i in range(40):
        d = client.get(f"/documents/{doc_id}", headers=headers)
        if d.status_code != 200:
            print(f"Poll failed: {d.status_code}")
            break
        status = d.json().get("status")
        chunks = d.json().get("chunk_count")
        print(f"  poll {i}: status={status} chunks={chunks}")
        if status == "completed":
            completed = True
            break
        if status == "failed":
            print(f"  error: {d.json().get('error_message')}")
            break
        time.sleep(3)

    if not completed:
        print("\nDocument not completed — ensure Celery worker is running:")
        print("  celery -A app.celery_app worker --loglevel=info")
        # Fallback: sync process for demo
        print("Attempting synchronous process_document_task...")
        from app.tasks.document_tasks import process_document_task
        upload_dir = ROOT / "uploads"
        tenant_dirs = list(upload_dir.glob("*"))
        file_path = None
        for td in tenant_dirs:
            p = td / f"{doc_id}.txt"
            if p.exists():
                file_path = str(p)
                tenant_id = td.name
                break
        if file_path:
            process_document_task(document_id=doc_id, file_path=file_path, tenant_id=tenant_id)
            completed = True
            print("Sync processing completed.")

    # Gateway search
    search_q = "品質管理"
    gs = client.post(
        "/gateway/search",
        headers=headers,
        json={"query": search_q, "top_k": 5, "domain": "hybrid"},
    )
    print(f"\nGateway search ({search_q}): {gs.status_code}")
    if gs.status_code == 200:
        data = gs.json()
        results = data.get("results", [])
        print(f"  results: {len(results)}")
        for i, r in enumerate(results[:3]):
            content = str(r.get("content", ""))[:80].encode("ascii", errors="replace").decode()
            print(f"  [{i}] score={r.get('score')} provider={r.get('provider')} {content}")
        adapters = data.get("audit_trail", {}).get("providers_called", [])
        print(f"  providers_called: {adapters}")
    else:
        print(gs.text[:400])

    # KB search fallback
    kb = client.post(
        "/kb/search",
        headers=headers,
        json={"query": search_q, "top_k": 5},
    )
    if kb.status_code == 200:
        kb_results = kb.json()
        print(f"KB search results: {len(kb_results) if isinstance(kb_results, list) else kb_results}")

    print("\n=== E2E complete ===")
    return 0 if completed and gs.status_code == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
