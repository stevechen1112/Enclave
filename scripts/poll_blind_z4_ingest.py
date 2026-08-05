"""Poll Blind Z4 document ingest status."""
from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path

import httpx

BASE = "http://localhost:8011"
UP = Path(__file__).resolve().parents[1] / "artifacts" / "blind_z4" / "upload_result.json"
OUT = Path(__file__).resolve().parents[1] / "artifacts" / "blind_z4" / "ingest_status.json"


def main(wait: bool = True, timeout_s: int = 900) -> int:
    up = json.loads(UP.read_text(encoding="utf-8"))["uploaded"]
    want = {r["name"]: r["id"] for r in up if r.get("ok")}
    client = httpx.Client(base_url=BASE, timeout=60.0)
    r = client.post(
        "/api/v1/auth/login/access-token",
        data={"username": "admin@enclave.local", "password": "admin123"},
    )
    r.raise_for_status()
    client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

    t0 = time.time()
    while True:
        docs = client.get("/api/v1/documents/", params={"limit": 400}).json()
        items = docs if isinstance(docs, list) else (docs.get("items") or docs.get("data") or [])
        by_id = {d.get("id"): d for d in items}
        by_name = {d.get("filename"): d for d in items}
        rows = []
        st: Counter[str] = Counter()
        for name, did in want.items():
            d = by_id.get(did) or by_name.get(name)
            status = (d or {}).get("status") or "MISSING"
            st[status] += 1
            rows.append(
                {
                    "name": name,
                    "id": did,
                    "status": status,
                    "chunk_count": (d or {}).get("chunk_count"),
                    "error_message": (d or {}).get("error_message"),
                }
            )
        summary = dict(st)
        print("status", summary, "elapsed", int(time.time() - t0), flush=True)
        OUT.write_text(
            json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        done = st.get("completed", 0)
        failed = st.get("failed", 0)
        if done + failed >= len(want):
            print("DONE", done, "failed", failed)
            return 0 if failed == 0 else 2
        if not wait or time.time() - t0 > timeout_s:
            print("TIMEOUT/ partial", summary)
            return 1
        time.sleep(15)


if __name__ == "__main__":
    import sys

    timeout_s = int(sys.argv[1]) if len(sys.argv) > 1 else 900
    raise SystemExit(main(wait=True, timeout_s=timeout_s))
