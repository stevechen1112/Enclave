"""B0b spike: prove DeepDOC extracts text from a scanned PDF that PlainText cannot.

Creates two throwaway RAGFlow datasets (PlainText vs DeepDOC), uploads the same
scanned PDF to both, parses, and reports chunk counts plus wall-clock time.

Usage:
  RAGFLOW_API_KEY=... python scripts/spike_deepdoc.py --pdf "<path>"
"""
import argparse
import json
import os
import pathlib
import time
import urllib.error
import urllib.request
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "artifacts" / "deepdoc_spike_last_run.json"
BASE = os.getenv("RAGFLOW_BASE_URL", "http://localhost:9380").rstrip("/")
KEY = os.getenv("RAGFLOW_API_KEY", "")

POLL_INTERVAL_S = 5
POLL_TIMEOUT_S = 1800
# Must match the live KB, otherwise RAGFlow rejects the parse task at bind time.
EMBEDDING_MODEL = os.getenv("RAGFLOW_EMBEDDING_MODEL", "bge-m3@ollama-local@Ollama")


def api(method: str, path: str, payload=None, raw_body=None, content_type=None):
    url = f"{BASE}{path}"
    headers = {"Authorization": f"Bearer {KEY}"}
    if payload is not None:
        raw_body = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    elif content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=raw_body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"code": e.code, "message": e.read().decode(errors="replace")}


def upload(dataset_id: str, pdf: pathlib.Path):
    boundary = uuid.uuid4().hex
    body = b"".join([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{pdf.name}"\r\n'.encode(),
        b"Content-Type: application/pdf\r\n\r\n",
        pdf.read_bytes(),
        f"\r\n--{boundary}--\r\n".encode(),
    ])
    return api("POST", f"/api/v1/datasets/{dataset_id}/documents",
               raw_body=body, content_type=f"multipart/form-data; boundary={boundary}")


def run_arm(name: str, layout: str, pdf: pathlib.Path) -> dict:
    ds_name = f"spike-{layout.lower().replace(' ', '')}-{uuid.uuid4().hex[:6]}"
    print(f"\n=== arm: {name} (layout_recognize={layout}) ===", flush=True)

    created = api("POST", "/api/v1/datasets", {
        "name": ds_name,
        "chunk_method": "naive",
        "embedding_model": EMBEDDING_MODEL,
        "parser_config": {"layout_recognize": layout, "chunk_token_num": 512, "delimiter": "\n"},
    })
    ds = (created.get("data") or {})
    ds_id = ds.get("id")
    if not ds_id:
        return {"arm": name, "error": f"dataset create failed: {created}"}
    print(f"  dataset={ds_id}", flush=True)

    up = upload(ds_id, pdf)
    docs = up.get("data") or []
    if not docs:
        return {"arm": name, "dataset_id": ds_id, "error": f"upload failed: {up}"}
    doc_id = docs[0].get("id")
    print(f"  uploaded doc={doc_id}", flush=True)

    t0 = time.time()
    api("POST", f"/api/v1/datasets/{ds_id}/documents/parse", {"document_ids": [doc_id]})

    status, chunks, msg = "UNKNOWN", 0, ""
    while time.time() - t0 < POLL_TIMEOUT_S:
        time.sleep(POLL_INTERVAL_S)
        listed = api("GET", f"/api/v1/datasets/{ds_id}/documents?page=1&page_size=10")
        rows = ((listed.get("data") or {}).get("docs") or [])
        if not rows:
            continue
        d = rows[0]
        status, chunks = d.get("run"), d.get("chunk_count") or 0
        msg = (d.get("progress_msg") or "").replace("\n", " ")[-300:]
        print(f"  [{time.time() - t0:6.0f}s] run={status} chunks={chunks} prog={d.get('progress')}", flush=True)
        if status in ("DONE", "FAIL", "CANCEL"):
            break
    elapsed = round(time.time() - t0, 1)

    sample = ""
    if chunks:
        got = api("GET", f"/api/v1/datasets/{ds_id}/documents/{doc_id}/chunks?page=1&page_size=3")
        items = ((got.get("data") or {}).get("chunks") or [])
        sample = " || ".join((c.get("content") or c.get("content_with_weight") or "")[:200] for c in items[:3])

    return {
        "arm": name, "layout_recognize": layout, "dataset_id": ds_id, "document_id": doc_id,
        "run": status, "chunk_count": chunks, "elapsed_s": elapsed,
        "progress_msg_tail": msg, "chunk_sample": sample,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--keep", action="store_true", help="keep the throwaway datasets")
    args = ap.parse_args()

    pdf = pathlib.Path(args.pdf)
    if not pdf.exists():
        print(f"missing pdf: {pdf}")
        return 2
    print(f"spike target: {pdf.name} ({pdf.stat().st_size} bytes)")

    arms = [run_arm("plaintext", "Plain Text", pdf), run_arm("deepdoc", "DeepDOC", pdf)]

    by = {a["arm"]: a for a in arms}
    pt, dd = by.get("plaintext", {}), by.get("deepdoc", {})
    verdict = "DEEPDOC_WINS" if dd.get("chunk_count", 0) > 0 and pt.get("chunk_count", 0) == 0 else "SEE_DETAIL"
    report = {
        "gate": "B0b-deepdoc-spike",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "target": {"name": pdf.name, "size": pdf.stat().st_size},
        "arms": arms,
        "verdict": verdict,
        "note": "single-document spike; feasibility + timing only, not a value proof (n=1)",
    }
    ARTIFACT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n" + json.dumps({k: report[k] for k in ("verdict",)}, ensure_ascii=False))
    print(f"PlainText: chunks={pt.get('chunk_count')} in {pt.get('elapsed_s')}s")
    print(f"DeepDOC  : chunks={dd.get('chunk_count')} in {dd.get('elapsed_s')}s")
    print(f"written: {ARTIFACT}")

    if not args.keep:
        for a in arms:
            if a.get("dataset_id"):
                api("DELETE", "/api/v1/datasets", {"ids": [a["dataset_id"]]})
        print("throwaway datasets deleted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
