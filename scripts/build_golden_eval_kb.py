"""P2 prerequisite: persistent golden-eval KB in RAGFlow.

Uploads the 12 Z1-1 annotated scanned PDFs into a PERSISTENT dataset
(name: enclave-golden-eval, DeepDOC) so retrieval ablation (E1) has a stable
target. Unlike eval_coverage/eval_parse_ablation, the dataset is NOT deleted.

Writes artifacts/golden_eval_kb.json with dataset_id and doc name->id mapping.
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from eval_coverage import api, upload, EMBEDDING_MODEL  # noqa: E402

ANNOTATION_DIR = ROOT / "testdata" / "golden" / "z1_scan_annotations"
ARTIFACT = ROOT / "artifacts" / "golden_eval_kb.json"
DATASET_NAME = "enclave-golden-eval"


def find_existing() -> str | None:
    page = 1
    while True:
        got = api("GET", f"/api/v1/datasets?page={page}&page_size=100")
        data = got.get("data")
        if isinstance(data, dict):
            items = data.get("datasets") or data.get("docs") or []
        elif isinstance(data, list):
            items = data
        else:
            items = []
        if not items:
            return None
        for d in items:
            if isinstance(d, dict) and d.get("name") == DATASET_NAME:
                return d.get("id")
        if len(items) < 100:
            return None
        page += 1


def main() -> int:
    docs = []
    for yml in sorted(ANNOTATION_DIR.glob("scan_*.yaml")):
        data = yaml.safe_load(yml.read_text(encoding="utf-8"))
        src = pathlib.Path(data["source_path"])
        if src.exists():
            docs.append({"id": data["id"], "path": src, "filename": data["filename"]})
    print(f"docs={len(docs)}")

    ds_id = find_existing()
    if ds_id:
        print(f"reusing existing dataset {ds_id}")
    else:
        created = api("POST", "/api/v1/datasets", {
            "name": DATASET_NAME,
            "chunk_method": "naive",
            "embedding_model": EMBEDDING_MODEL,
            "parser_config": {"layout_recognize": "DeepDOC", "chunk_token_num": 512, "delimiter": "\n"},
        })
        ds_id = (created.get("data") or {}).get("id")
        if not ds_id:
            print(f"dataset create failed: {created}")
            return 1
        print(f"created dataset {ds_id}")

    # skip docs already present by name
    existing = {}
    page = 1
    while True:
        listed = api("GET", f"/api/v1/datasets/{ds_id}/documents?page={page}&page_size=100")
        batch = (listed.get("data") or {}).get("docs") or []
        if not batch:
            break
        for d in batch:
            existing[d.get("name")] = d
        page += 1

    name_to_id = {name: d["id"] for name, d in existing.items()}
    to_upload = [d for d in docs if d["filename"] not in existing]
    print(f"already present={len(existing)} to_upload={len(to_upload)}")

    new_ids = []
    for d in to_upload:
        up = upload(ds_id, d["path"])
        items = up.get("data") or []
        if items:
            name_to_id[d["filename"]] = items[0]["id"]
            new_ids.append(items[0]["id"])
            print(f"  uploaded {d['filename']}")
        else:
            print(f"  UPLOAD FAILED {d['filename']}: {up}")

    if new_ids:
        api("POST", f"/api/v1/datasets/{ds_id}/documents/parse", {"document_ids": new_ids})

    t0 = time.time()
    while time.time() - t0 < 7200:
        time.sleep(10)
        rows, page = {}, 1
        while True:
            listed = api("GET", f"/api/v1/datasets/{ds_id}/documents?page={page}&page_size=100")
            batch = (listed.get("data") or {}).get("docs") or []
            if not batch:
                break
            for d in batch:
                rows[d["id"]] = d
            page += 1
        pending = [d for d in rows.values() if d.get("run") not in ("DONE", "FAIL", "CANCEL")]
        print(f"  [{time.time() - t0:5.0f}s] settled {len(rows) - len(pending)}/{len(rows)}", flush=True)
        if not pending:
            time.sleep(15)
            break

    final, page = {}, 1
    while True:
        listed = api("GET", f"/api/v1/datasets/{ds_id}/documents?page={page}&page_size=100")
        batch = (listed.get("data") or {}).get("docs") or []
        if not batch:
            break
        for d in batch:
            final[d["id"]] = d
        page += 1

    report = {
        "dataset_id": ds_id,
        "dataset_name": DATASET_NAME,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "documents": {
            d["id"]: {"name": d.get("name"), "run": d.get("run"),
                      "chunk_count": d.get("chunk_count")}
            for d in final.values()
        },
    }
    ARTIFACT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = sum(1 for d in final.values() if d.get("run") == "DONE" and (d.get("chunk_count") or 0) > 0)
    print(f"\ndataset={ds_id} docs={len(final)} with_chunks={ok}")
    print(f"written: {ARTIFACT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
