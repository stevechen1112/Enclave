"""Wait until Blind Z3 uploads reach completed (or timeout)."""
from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path

import httpx

BASE = "http://localhost:8001"
UPLOAD = Path(__file__).resolve().parents[1] / "artifacts" / "blind_z3" / "upload_result.json"


def main() -> None:
    ids = [r["id"] for r in json.loads(UPLOAD.read_text(encoding="utf-8"))["uploaded"] if r.get("id")]
    client = httpx.Client(base_url=BASE, timeout=60.0)
    for user in ("admin@enclave.local", "admin@example.com"):
        r = client.post(
            "/api/v1/auth/login/access-token",
            data={"username": user, "password": "admin123"},
        )
        if r.status_code == 200:
            client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
            break
    else:
        raise SystemExit("login failed")

    t0 = time.time()
    while time.time() - t0 < 900:
        statuses = []
        for did in ids:
            resp = client.get(f"/api/v1/documents/{did}")
            if resp.status_code != 200:
                statuses.append("http_err")
                continue
            d = resp.json()
            statuses.append(d.get("status") or d.get("processing_status") or "?")
        c = Counter(statuses)
        print(f"t={int(time.time()-t0)}s {dict(c)}")
        done = c.get("completed", 0) + c.get("ready", 0) + c.get("indexed", 0)
        # also accept failed as terminal
        terminal = done + c.get("failed", 0) + c.get("error", 0)
        if terminal >= len(ids):
            print("ALL_TERMINAL")
            break
        time.sleep(10)
    else:
        print("TIMEOUT")


if __name__ == "__main__":
    main()
