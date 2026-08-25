"""Upload Blind Z4 hold-out corpus via /documents/upload."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx

BASE = "http://localhost:8011"
MANIFEST = Path(__file__).resolve().parents[1] / "artifacts" / "blind_z4" / "corpus_manifest.json"
OUT = Path(__file__).resolve().parents[1] / "artifacts" / "blind_z4" / "upload_result.json"
EMAIL = "admin@enclave.local"
PASSWORD = os.environ["BLIND_EVAL_PASSWORD"]


def main() -> None:
    files = json.loads(MANIFEST.read_text(encoding="utf-8"))["files"]
    client = httpx.Client(base_url=BASE, timeout=180.0)
    for user in (EMAIL, "admin@example.com"):
        r = client.post(
            "/api/v1/auth/login/access-token",
            data={"username": user, "password": PASSWORD},
        )
        if r.status_code == 200:
            print("login ok", user)
            client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
            break
    else:
        raise SystemExit(f"login failed: {r.status_code} {r.text[:200]}")

    results = []
    for i, f in enumerate(files, 1):
        path = Path(f["path"])
        if not path.exists():
            results.append({"i": i, "name": f["name"], "ok": False, "error": "missing"})
            print(f"{i:02d} MISSING {f['name']}")
            continue
        with path.open("rb") as fh:
            resp = client.post(
                "/api/v1/documents/upload",
                files={"file": (f["name"], fh, "application/octet-stream")},
            )
        ok = resp.status_code == 200
        doc_id = None
        err = None
        if ok:
            doc_id = resp.json().get("id")
            print(f"{i:02d} OK  {f['name'][:60]} -> {doc_id}", flush=True)
        else:
            err = f"{resp.status_code} {resp.text[:180]}"
            print(f"{i:02d} FAIL {f['name'][:60]} {err}", flush=True)
        results.append(
            {
                "i": i,
                "name": f["name"],
                "ok": ok,
                "id": doc_id,
                "error": err,
                "root": f["root"],
                "catalog_id": f"z4-doc-{i:02d}",
            }
        )
        time.sleep(0.35)

    OUT.write_text(json.dumps({"uploaded": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    ok_n = sum(1 for r in results if r["ok"])
    print(f"DONE {ok_n}/{len(results)} -> {OUT}")


if __name__ == "__main__":
    main()
