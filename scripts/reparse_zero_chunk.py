"""B2 — re-parse zero-chunk DONE documents now that the KB uses DeepDOC.

After B1 switched the production KB to ``layout_recognize=DeepDOC``, documents
that previously parsed to 0 chunks under Plain Text (scanned PDFs with no text
layer) must be re-parsed so DeepDOC's OCR/layout pipeline actually runs. This
script targets every document in the production KB whose run=DONE but
chunk_count=0, triggers a re-parse, and polls until each settles.

Run with ``--apply`` to execute; default is a dry run listing the targets.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "artifacts" / "reparse_zero_chunk_last_run.json"
POLL_INTERVAL_S = 10
POLL_TIMEOUT_S = 1800  # DeepDOC on scanned pages is slow; allow 30 min


def _load_env() -> None:
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def _list_docs(client, base, headers, dsid):
    docs, page = [], 1
    while True:
        r = client.get(f"{base}/api/v1/datasets/{dsid}/documents?page={page}&page_size=100",
                       headers=headers)
        r.raise_for_status()
        batch = r.json().get("data", {}).get("docs", [])
        if not batch:
            break
        docs.extend(batch)
        page += 1
    return docs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    _load_env()
    base = os.environ.get("RAGFLOW_BASE_URL", "http://localhost:9380").rstrip("/")
    key = os.environ.get("RAGFLOW_API_KEY", "")
    dsid = os.environ.get("RAGFLOW_DATASET_ID", "")
    if not (key and dsid):
        print("RAGFLOW_API_KEY / RAGFLOW_DATASET_ID required")
        return 1
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    with httpx.Client(timeout=60) as client:
        docs = _list_docs(client, base, headers, dsid)
        # Targets: DONE but produced nothing (the false-DONE scanned files).
        targets = [d for d in docs if d.get("run") == "DONE" and d.get("chunk_count", 0) == 0]
        print(f"total docs={len(docs)}  zero-chunk DONE targets={len(targets)}")
        for d in targets:
            print(f"  target id={d['id']} name={d.get('name','')[:50]}")

        if not targets:
            print("nothing to re-parse")
            return 0
        if not args.apply:
            print("DRY RUN — re-run with --apply to re-parse.")
            return 0

        ids = [d["id"] for d in targets]

        # Each document snapshots parser_config at upload time, so the dataset-level
        # DeepDOC switch (B1) does NOT reach existing docs. Flip the doc-level
        # layout_recognize too, otherwise the re-parse still runs Plain Text.
        for d in targets:
            doc_pc = d.get("parser_config") or {}
            if doc_pc.get("layout_recognize") == "DeepDOC":
                continue
            pr = client.put(
                f"{base}/api/v1/datasets/{dsid}/documents/{d['id']}",
                headers=headers,
                json={"parser_config": {"layout_recognize": "DeepDOC"}},
            )
            if pr.status_code != 200 or pr.json().get("code") not in (0, None):
                print(f"doc {d['id']} config update failed: {pr.status_code} {pr.text[:200]}")
                return 1
            print(f"  doc {d['id'][:8]} layout_recognize -> DeepDOC")

        r = client.post(f"{base}/api/v1/datasets/{dsid}/chunks",
                        headers=headers, json={"document_ids": ids})
        if r.status_code != 200 or r.json().get("code") not in (0, None):
            print(f"trigger failed: {r.status_code} {r.text[:300]}")
            return 1
        print(f"re-parse triggered for {len(ids)} docs; polling...")

        deadline = time.time() + POLL_TIMEOUT_S
        settled = {}
        while time.time() < deadline:
            time.sleep(POLL_INTERVAL_S)
            docs = {d["id"]: d for d in _list_docs(client, base, headers, dsid)}
            for did in ids:
                d = docs.get(did)
                if not d:
                    continue
                run = d.get("run")
                if run in ("DONE", "FAIL", "CANCEL"):
                    settled[did] = d
            if len(settled) == len(ids):
                break
            pending = len(ids) - len(settled)
            print(f"  ...{pending} still running")

        # DeepDOC flushes chunks shortly after run=DONE; give it a grace window.
        time.sleep(15)
        docs = {d["id"]: d for d in _list_docs(client, base, headers, dsid)}
        results = []
        for did in ids:
            d = docs.get(did, {})
            results.append({
                "id": did,
                "name": d.get("name"),
                "run": d.get("run"),
                "chunk_count": d.get("chunk_count"),
                "progress_msg": d.get("progress_msg"),
            })
            print(f"  final id={did} run={d.get('run')} chunks={d.get('chunk_count')} "
                  f"msg={str(d.get('progress_msg'))[:60]}")

        ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
        ARTIFACT.write_text(json.dumps({"results": results}, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        still_zero = [r for r in results if r.get("run") == "DONE" and not r.get("chunk_count")]
        print(f"\nwritten {ARTIFACT.name}; still zero-chunk DONE: {len(still_zero)}")
        return 0 if not still_zero else 2


if __name__ == "__main__":
    raise SystemExit(main())
