"""Re-queue Blind Z4 docs stuck in non-terminal status."""
from __future__ import annotations

import json
from pathlib import Path

import httpx

BASE = "http://localhost:8011"
ROOT = Path(__file__).resolve().parents[2]
UP = ROOT / "artifacts" / "blind_z4" / "upload_result.json"
TERMINAL = {"completed", "failed"}


def main() -> None:
    up = json.loads(UP.read_text(encoding="utf-8"))["uploaded"]
    want = {r["id"]: r["name"] for r in up if r.get("ok")}
    c = httpx.Client(base_url=BASE, timeout=60)
    r = c.post(
        "/api/v1/auth/login/access-token",
        data={"username": "admin@enclave.local", "password": "admin123"},
    )
    r.raise_for_status()
    token = r.json()["access_token"]
    c.headers["Authorization"] = f"Bearer {token}"
    items = c.get("/api/v1/documents/", params={"limit": 400}).json()
    items = items if isinstance(items, list) else (items.get("items") or items.get("data") or [])
    by_id = {d["id"]: d for d in items}
    stuck = []
    for did, name in want.items():
        d = by_id.get(did)
        st = (d or {}).get("status") or "MISSING"
        if st not in TERMINAL:
            stuck.append((did, name, st, (d or {}).get("file_path")))
    print(f"stuck={len(stuck)}")
    for did, name, st, fp in stuck:
        print(f"  {st}: {name[:60]}")
    # Dispatch via docker worker python
    out = ROOT / "artifacts" / "blind_z4" / "_stuck_ids.json"
    out.write_text(
        json.dumps(
            [{"id": did, "name": n, "status": s, "file_path": fp} for did, n, s, fp in stuck],
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
