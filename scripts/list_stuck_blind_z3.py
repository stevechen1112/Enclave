"""Re-queue Blind Z3 docs stuck in uploading/parsing (lost celery tasks)."""
from __future__ import annotations

import json
from pathlib import Path

import httpx

BASE = "http://localhost:8001"
UPLOAD = Path(__file__).resolve().parents[1] / "artifacts" / "blind_z3" / "upload_result.json"


def main() -> None:
    ids = [r["id"] for r in json.loads(UPLOAD.read_text(encoding="utf-8"))["uploaded"] if r.get("id")]
    client = httpx.Client(base_url=BASE, timeout=60.0)
    r = client.post(
        "/api/v1/auth/login/access-token",
        data={"username": "admin@enclave.local", "password": "admin123"},
    )
    r.raise_for_status()
    client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

    stuck = []
    for did in ids:
        d = client.get(f"/api/v1/documents/{did}").json()
        if d.get("status") in {"uploading", "parsing", "embedding", "pending", "uploaded"}:
            stuck.append(d)
            print(d["status"], d.get("filename", "")[:60], did)

    Path("artifacts/blind_z3/stuck_docs.json").write_text(
        json.dumps(stuck, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("stuck", len(stuck))


if __name__ == "__main__":
    main()
