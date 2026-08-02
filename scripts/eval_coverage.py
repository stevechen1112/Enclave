"""Z0-4 / CV-RF-01a: coverage + CER ablation, PlainText vs DeepDOC.

Runs both parser arms over the same corpus in RAGFlow and reports metrics that need
no manual annotation:
  - zero-chunk rate (a zero-chunk document is unretrievable)
  - extracted characters per page
  - character error rate against ground truth (synthetic-scan corpus only)

Corpora:
  --corpus synthetic  golden synthetic scans, ground truth available -> CER reported
  --corpus real       golden real scanned PDFs, no ground truth -> coverage only

Usage:
  RAGFLOW_API_KEY=... python scripts/eval_coverage.py --corpus synthetic
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from app.eval import character_error_rate, judge  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "testdata" / "golden"
ARTIFACT = ROOT / "artifacts" / "coverage_ablation_last_run.json"

BASE = os.getenv("RAGFLOW_BASE_URL", "http://localhost:9380").rstrip("/")
KEY = os.getenv("RAGFLOW_API_KEY", "")
EMBEDDING_MODEL = os.getenv("RAGFLOW_EMBEDDING_MODEL", "bge-m3@ollama-local@Ollama")

POLL_INTERVAL_S = 10
POLL_TIMEOUT_S = 7200
ZERO_CHUNK_MAX = float(os.getenv("CV_RF01A_ZERO_CHUNK_MAX", "0.05"))
CER_MAX = float(os.getenv("CV_RF01A_CER_MAX", "0.35"))


def api(method: str, path: str, payload=None, raw_body=None, content_type=None):
    headers = {"Authorization": f"Bearer {KEY}"}
    if payload is not None:
        raw_body = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    elif content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(f"{BASE}{path}", data=raw_body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"code": e.code, "message": e.read().decode(errors="replace")}


def upload(dataset_id: str, path: pathlib.Path):
    boundary = uuid.uuid4().hex
    body = b"".join([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'.encode(),
        b"Content-Type: application/pdf\r\n\r\n",
        path.read_bytes(),
        f"\r\n--{boundary}--\r\n".encode(),
    ])
    return api("POST", f"/api/v1/datasets/{dataset_id}/documents",
               raw_body=body, content_type=f"multipart/form-data; boundary={boundary}")


def all_chunk_text(dataset_id: str, doc_id: str) -> str:
    parts, page = [], 1
    while True:
        got = api("GET", f"/api/v1/datasets/{dataset_id}/documents/{doc_id}/chunks?page={page}&page_size=100")
        items = ((got.get("data") or {}).get("chunks") or [])
        if not items:
            break
        parts.extend((c.get("content") or c.get("content_with_weight") or "") for c in items)
        page += 1
    return "\n".join(parts)


def run_arm(layout: str, files: list[tuple[str, pathlib.Path]]) -> dict:
    ds_name = f"cov-{layout.lower().replace(' ', '')}-{uuid.uuid4().hex[:6]}"
    created = api("POST", "/api/v1/datasets", {
        "name": ds_name,
        "chunk_method": "naive",
        "embedding_model": EMBEDDING_MODEL,
        "parser_config": {"layout_recognize": layout, "chunk_token_num": 512, "delimiter": "\n"},
    })
    ds_id = (created.get("data") or {}).get("id")
    if not ds_id:
        raise RuntimeError(f"dataset create failed: {created}")
    print(f"  dataset={ds_id} ({layout})", flush=True)

    doc_ids = {}
    for doc_key, path in files:
        up = upload(ds_id, path)
        docs = up.get("data") or []
        if docs:
            doc_ids[docs[0]["id"]] = doc_key
        else:
            print(f"    upload failed: {path.name} -> {up}", flush=True)

    t0 = time.time()
    api("POST", f"/api/v1/datasets/{ds_id}/documents/parse", {"document_ids": list(doc_ids)})

    rows = {}
    while time.time() - t0 < POLL_TIMEOUT_S:
        time.sleep(POLL_INTERVAL_S)
        rows, page = {}, 1
        while True:
            listed = api("GET", f"/api/v1/datasets/{ds_id}/documents?page={page}&page_size=100")
            batch = ((listed.get("data") or {}).get("docs") or [])
            if not batch:
                break
            for d in batch:
                rows[d["id"]] = d
            page += 1
        pending = [d for d in rows.values() if d.get("run") not in ("DONE", "FAIL", "CANCEL")]
        done = len(rows) - len(pending)
        print(f"  [{time.time() - t0:6.0f}s] {layout}: {done}/{len(rows)} settled", flush=True)
        if not pending:
            # RAGFlow marks run=DONE before the final chunk write is visible to the
            # chunks endpoint; wait briefly so we do not read an empty result set.
            print(f"  [{time.time() - t0:6.0f}s] {layout}: all settled, waiting for chunk flush...", flush=True)
            time.sleep(15)
            break
    elapsed = round(time.time() - t0, 1)

    per_doc = {}
    for doc_id, d in rows.items():
        key = doc_ids.get(doc_id, doc_id)
        text = all_chunk_text(ds_id, doc_id) if d.get("chunk_count") else ""
        per_doc[key] = {
            "run": d.get("run"),
            "chunk_count": d.get("chunk_count") or 0,
            "extracted_chars": len(text),
            "text": text,
        }
    return {"dataset_id": ds_id, "layout_recognize": layout, "elapsed_s": elapsed, "per_doc": per_doc}


def _strip_text(per_doc: dict) -> dict:
    """Remove the bulky text field before writing the artifact; keep it in memory."""
    return {k: {kk: vv for kk, vv in v.items() if kk != "text"} for k, v in per_doc.items()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", choices=["synthetic", "real"], default="synthetic")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    ground_truth: dict[str, str] = {}
    pages: dict[str, int] = {}

    if args.corpus == "synthetic":
        man = json.loads((GOLDEN / "synthetic_manifest.json").read_text(encoding="utf-8"))
        snapshot = man["corpus_snapshot_id"]
        base = GOLDEN / "synthetic_scans"
        files = []
        for r in man["documents"]:
            files.append((r["id"], base / r["synthetic_file"]))
            ground_truth[r["id"]] = (base / r["ground_truth_file"]).read_text(encoding="utf-8")
            pages[r["id"]] = r["pages"]
    else:
        man = json.loads((GOLDEN / "manifest.json").read_text(encoding="utf-8"))
        snapshot = man["corpus_snapshot_id"]
        base = GOLDEN / "files"
        files = [(d["id"], base / d["file"]) for d in man["documents"]
                 if d["kind"] == "scanned" and d["ext"] == ".pdf"]
        pages = {d["id"]: (d.get("pages") or 0) for d in man["documents"]}

    if args.limit:
        files = files[: args.limit]
    print(f"corpus={args.corpus} documents={len(files)} snapshot={snapshot}")

    arms = {}
    for layout in ("Plain Text", "DeepDOC"):
        print(f"\n=== arm {layout} ===", flush=True)
        arms[layout] = run_arm(layout, files)

    keys = [k for k, _ in files]
    summary, per_doc_report = {}, []
    for layout, arm in arms.items():
        zero = sum(1 for k in keys if arm["per_doc"].get(k, {}).get("chunk_count", 0) == 0)
        chars = sum(arm["per_doc"].get(k, {}).get("extracted_chars", 0) for k in keys)
        total_pages = sum(pages.get(k, 0) for k in keys) or 1
        entry = {
            "zero_chunk_docs": zero,
            "zero_chunk_rate": round(zero / len(keys), 4) if keys else 1.0,
            "extracted_chars": chars,
            "chars_per_page": round(chars / total_pages, 1),
            "elapsed_s": arm["elapsed_s"],
        }
        if ground_truth:
            cers = [character_error_rate(ground_truth[k], arm["per_doc"].get(k, {}).get("text", ""))
                    for k in keys if k in ground_truth]
            entry["mean_cer"] = round(sum(cers) / len(cers), 4) if cers else 1.0
        summary[layout] = entry

    for k in keys:
        row = {"id": k, "pages": pages.get(k)}
        for layout, arm in arms.items():
            d = arm["per_doc"].get(k, {})
            tag = "plaintext" if layout == "Plain Text" else "deepdoc"
            row[f"{tag}_chunks"] = d.get("chunk_count", 0)
            row[f"{tag}_chars"] = d.get("extracted_chars", 0)
            if k in ground_truth:
                row[f"{tag}_cer"] = round(character_error_rate(ground_truth[k], d.get("text", "")), 4)
        per_doc_report.append(row)

    # Keep the extracted text in the artifact so downstream gates can audit it.
    for layout, arm in arms.items():
        arm["per_doc"] = _strip_text(arm["per_doc"])

    # A document "covered" means it produced at least one chunk, i.e. it is retrievable.
    base_ok = sum(1 for r in per_doc_report if r["plaintext_chunks"] > 0)
    treat_ok = sum(1 for r in per_doc_report if r["deepdoc_chunks"] > 0)
    only_base = sum(1 for r in per_doc_report if r["plaintext_chunks"] > 0 and r["deepdoc_chunks"] == 0)
    only_treat = sum(1 for r in per_doc_report if r["deepdoc_chunks"] > 0 and r["plaintext_chunks"] == 0)

    verdict = judge(base_ok, treat_ok, len(per_doc_report), threshold=0.20,
                    discordant=(only_base, only_treat))

    dd = summary.get("DeepDOC", {})
    gate_pass = (
        verdict.judgement == "PROVEN"
        and dd.get("zero_chunk_rate", 1.0) <= ZERO_CHUNK_MAX
        and (dd.get("mean_cer", 0.0) <= CER_MAX if ground_truth else True)
    )

    report = {
        "gate": "CV-RF-01a",
        "status": "PASS" if gate_pass else "FAIL",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "corpus": f"{args.corpus}_scan",
        "corpus_snapshot_id": snapshot,
        "golden_tier": 0,
        "n": len(per_doc_report),
        "embedding_model": EMBEDDING_MODEL,
        "thresholds": {"zero_chunk_rate_max": ZERO_CHUNK_MAX, "mean_cer_max": CER_MAX,
                       "coverage_delta_min": 0.20},
        "summary": summary,
        "coverage_judgement": verdict.as_dict(),
        "per_document": per_doc_report,
    }
    ARTIFACT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    print("\n===== RESULT =====")
    for layout, s in summary.items():
        print(f"  {layout:11s} zero_chunk={s['zero_chunk_rate']:.1%} chars/page={s['chars_per_page']:>7} "
              f"cer={s.get('mean_cer', '-')} elapsed={s['elapsed_s']}s")
    print(f"  coverage judgement = {verdict.judgement} (delta={verdict.delta:+.1%}, CI low={verdict.ci_low:+.3f})")
    print(f"  gate status = {report['status']}")
    print(f"written: {ARTIFACT}")

    if not args.keep:
        for arm in arms.values():
            api("DELETE", "/api/v1/datasets", {"ids": [arm["dataset_id"]]})
        print("throwaway datasets deleted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
