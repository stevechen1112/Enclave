"""Ingest the 12 Z1 golden scan files into the running stack for
answer-correctness acceptance (eval_answer_correctness.py).

Uploads each file from testdata/golden/files via /api/v1/documents/upload
(auto_process=true) and polls until parse+index completes.
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

import httpx

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "testdata" / "golden" / "z1_scan_annotations" / "manifest.json"
BASE = "http://localhost:8001"


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true",
                    help="Delete existing completed/failed docs and re-upload")
    ap.add_argument("--only", nargs="*", default=None,
                    help="Optional filename substrings to include")
    args = ap.parse_args()

    entries = json.loads(MANIFEST.read_text(encoding="utf-8"))["entries"]
    client = httpx.Client(base_url=BASE, timeout=120.0)
    r = client.post("/api/v1/auth/login/access-token",
                    data={"username": "admin@example.com", "password": "admin123"})
    r.raise_for_status()
    client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

    online = {d.get("filename"): d for d in client.get("/api/v1/documents/", params={"limit": 200}).json()}
    pending: dict[str, str] = {}  # doc_id -> name
    for e in entries:
        name = e["name"]
        if args.only and not any(s in name for s in args.only):
            continue
        existing = online.get(name)
        if existing and existing.get("status") == "completed" and not args.force:
            qr = existing.get("quality_report") or {}
            eng = qr.get("parse_engine") if isinstance(qr, dict) else None
            print(f"skip (already completed engine={eng}): {name}", flush=True)
            continue
        if existing and (existing.get("status") == "failed" or args.force):
            client.delete(f"/api/v1/documents/{existing['id']}")
            print(f"deleted existing doc: {name}", flush=True)
        fp = pathlib.Path(e["path"])
        if not fp.exists():
            print(f"MISSING FILE: {fp}", flush=True)
            continue
        with open(fp, "rb") as fh:
            resp = client.post("/api/v1/documents/upload",
                               files={"file": (fp.name, fh, "application/octet-stream")},
                               data={"auto_process": "true"})
        if resp.status_code not in (200, 201):
            print(f"upload FAILED {name}: {resp.status_code} {resp.text[:150]}", flush=True)
            continue
        doc_id = resp.json().get("id") or resp.json().get("document_id")
        pending[doc_id] = name
        print(f"uploaded: {name} -> {doc_id}", flush=True)

    deadline = time.time() + 1800
    while pending and time.time() < deadline:
        time.sleep(15)
        for doc_id, name in list(pending.items()):
            d = client.get(f"/api/v1/documents/{doc_id}").json()
            status = d.get("status")
            if status in ("completed", "failed"):
                qr = d.get("quality_report") or {}
                eng = qr.get("parse_engine") if isinstance(qr, dict) else None
                ocr = qr.get("ocr_used") if isinstance(qr, dict) else None
                print(f"{status}: {name} engine={eng} ocr={ocr}", flush=True)
                del pending[doc_id]
        if pending:
            print(f"waiting on {len(pending)} docs...", flush=True)

    if pending:
        print("TIMEOUT waiting for:", list(pending.values()), flush=True)
        return 1
    print("all golden scans ingested", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
