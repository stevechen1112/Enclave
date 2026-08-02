"""CV-RF-02 — chunk_method ablation: naive vs laws / manual / table.

Same 12 golden scans, DeepDOC layout, only chunk_method differs.
Scores Hit@5 on Z1-2 factual + table_lookup + multi_hop questions.

PASS: any treatment arm Hit@5 Δ ≥ +10pp vs naive with CI support (McNemar).

Writes artifacts/chunk_template_ablation_last_run.json.
"""
from __future__ import annotations

import json
import pathlib
import sys
import time
import uuid

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from app.eval import hit_at_k, judge  # noqa: E402
from eval_coverage import api, upload, EMBEDDING_MODEL  # noqa: E402

ANNOTATION_DIR = ROOT / "testdata" / "golden" / "z1_scan_annotations"
QUESTIONS = ROOT / "testdata" / "golden" / "z1_retrieve_questions.yaml"
ARTIFACT = ROOT / "artifacts" / "chunk_template_ablation_last_run.json"
TOP_K = 5
DELTA_MIN = 0.10
ARMS = ("naive", "laws", "manual", "table")


def load_docs():
    docs = []
    for yml in sorted(ANNOTATION_DIR.glob("scan_*.yaml")):
        data = yaml.safe_load(yml.read_text(encoding="utf-8"))
        src = pathlib.Path(data["source_path"])
        if src.exists():
            docs.append({"id": data["id"], "path": src, "filename": data["filename"]})
    return docs


def run_arm(method: str, docs: list) -> dict:
    created = api("POST", "/api/v1/datasets", {
        "name": f"chunk-{method}-{uuid.uuid4().hex[:6]}",
        "chunk_method": method,
        "embedding_model": EMBEDDING_MODEL,
        "parser_config": {
            "layout_recognize": "DeepDOC",
            "chunk_token_num": 512,
            "delimiter": "\n",
        },
    })
    ds_id = (created.get("data") or {}).get("id")
    if not ds_id:
        raise RuntimeError(f"create failed for {method}: {created}")
    print(f"  dataset={ds_id} method={method}", flush=True)
    ids = []
    for d in docs:
        up = upload(ds_id, d["path"])
        items = up.get("data") or []
        if items:
            ids.append(items[0]["id"])
    api("POST", f"/api/v1/datasets/{ds_id}/documents/parse", {"document_ids": ids})
    t0 = time.time()
    while time.time() - t0 < 7200:
        time.sleep(10)
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
        print(f"  [{time.time()-t0:5.0f}s] {method}: {len(rows)-len(pending)}/{len(rows)}", flush=True)
        if not pending:
            time.sleep(15)
            break
    chunks = sum(int(d.get("chunk_count") or 0) for d in rows.values())
    return {"dataset_id": ds_id, "elapsed_s": round(time.time() - t0, 1), "total_chunks": chunks}


def retrieve(ds_id: str, query: str, file_to_scan: dict) -> list[str]:
    got = api("POST", "/api/v1/retrieval", {
        "question": query,
        "dataset_ids": [ds_id],
        "top_k": TOP_K,
        "similarity_threshold": 0.0,
        "vector_similarity_weight": 0.3,
    })
    ranked = []
    for c in (got.get("data") or {}).get("chunks") or []:
        name = c.get("document_keyword") or c.get("docnm_kwd") or ""
        scan = file_to_scan.get(name)
        if scan and scan not in ranked:
            ranked.append(scan)
    return ranked


def main() -> int:
    docs = load_docs()
    file_to_scan = {d["filename"]: d["id"] for d in docs}
    qs = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))["questions"]
    targets = [q for q in qs
               if q["category"] in ("factual", "table_lookup", "multi_hop")
               and (q.get("expected") or {}).get("document_ids")]

    arms = {}
    for method in ARMS:
        print(f"\n=== arm {method} ===", flush=True)
        arms[method] = run_arm(method, docs)

    hits = {m: [] for m in ARMS}
    per_q = []
    for q in targets:
        relevant = q["expected"]["document_ids"]
        row = {"id": q["id"], "query": q["query"], "relevant": relevant}
        for m in ARMS:
            ranked = retrieve(arms[m]["dataset_id"], q["query"], file_to_scan)
            ok = hit_at_k(ranked, relevant, TOP_K) > 0
            hits[m].append(ok)
            row[f"{m}_hit"] = ok
            row[f"{m}_ranked"] = ranked
        per_q.append(row)
        print("  " + q["id"] + " " + " ".join(
            f"{m[0]}={'Y' if hits[m][-1] else '-'}" for m in ARMS), flush=True)

    n = len(targets)
    judgements = {}
    base = hits["naive"]
    best_arm, best_v = "naive", None
    for m in ARMS:
        if m == "naive":
            continue
        only_base = sum(1 for b, t in zip(base, hits[m]) if b and not t)
        only_treat = sum(1 for b, t in zip(base, hits[m]) if t and not b)
        v = judge(sum(base), sum(hits[m]), n, threshold=DELTA_MIN,
                  min_n=5, discordant=(only_base, only_treat))
        judgements[f"naive_vs_{m}"] = v.as_dict()
        if best_v is None or v.delta > best_v.delta:
            best_arm, best_v = m, v

    status = "PASS" if best_v and best_v.judgement == "PROVEN" else "FAIL"
    report = {
        "gate": "CV-RF-02",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "status": status,
        "n_questions": n,
        "summary": {
            m: {"hit_at_5": round(sum(hits[m]) / n, 4) if n else 0,
                "total_chunks": arms[m]["total_chunks"],
                "elapsed_s": arms[m]["elapsed_s"]}
            for m in ARMS
        },
        "judgements": judgements,
        "best_treatment": best_arm,
        "best_judgement": best_v.as_dict() if best_v else None,
        "per_question": per_q,
        "datasets": {m: arms[m]["dataset_id"] for m in ARMS},
        "product_default": "naive",
    }
    ARTIFACT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n===== CV-RF-02 RESULT =====")
    for m in ARMS:
        s = report["summary"][m]
        print(f"  {m:8s} hit@5={s['hit_at_5']:.1%} chunks={s['total_chunks']}")
    for name, j in judgements.items():
        print(f"  {name}: {j['judgement']} delta={j['delta']:+.1%}")
    print(f"  status={status} best={best_arm}")
    print(f"written: {ARTIFACT}")
    for arm in arms.values():
        api("DELETE", "/api/v1/datasets", {"ids": [arm["dataset_id"]]})
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
