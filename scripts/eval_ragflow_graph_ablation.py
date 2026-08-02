"""CV-RF-05 — RAGFlow GraphRAG ablation on enclave-golden-eval.

Baseline: golden-eval KB retrieval (no graph index).
Treatment: throwaway clone + POST .../index?type=graph, then retrieval with
optional use_kg if the API accepts it.

Writes artifacts/ragflow_graph_ablation_last_run.json.
Product default remains OFF regardless of outcome.
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
KB_ARTIFACT = ROOT / "artifacts" / "golden_eval_kb.json"
ARTIFACT = ROOT / "artifacts" / "ragflow_graph_ablation_last_run.json"
TOP_K = 5
DELTA_MIN = 0.15
GRAPH_TIMEOUT_S = 1800


def load_docs():
    docs = []
    for yml in sorted(ANNOTATION_DIR.glob("scan_*.yaml")):
        data = yaml.safe_load(yml.read_text(encoding="utf-8"))
        src = pathlib.Path(data["source_path"])
        if src.exists():
            docs.append({"id": data["id"], "path": src, "filename": data["filename"]})
    return docs


def wait_parse(ds_id: str, n: int) -> None:
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
        print(f"  [{time.time()-t0:5.0f}s] parse {len(rows)-len(pending)}/{len(rows)}", flush=True)
        if not pending and len(rows) >= n:
            time.sleep(15)
            return


def wait_graph(ds_id: str) -> dict:
    t0 = time.time()
    last = {}
    while time.time() - t0 < GRAPH_TIMEOUT_S:
        time.sleep(15)
        got = api("GET", f"/api/v1/datasets/{ds_id}/index?type=graph")
        last = got
        data = got.get("data") or got
        status = ""
        if isinstance(data, dict):
            status = str(data.get("status") or data.get("run") or data.get("progress") or "")
        print(f"  [{time.time()-t0:5.0f}s] graph status={status!r} code={got.get('code')}", flush=True)
        s = status.lower().strip()
        try:
            prog = float(s)
            if prog < 0:
                return {"ok": False, "note": "graph_progress_negative", "elapsed_s": round(time.time()-t0, 1), "raw": got}
            if prog >= 1.0:
                return {"ok": True, "elapsed_s": round(time.time()-t0, 1), "raw": got}
        except ValueError:
            pass
        if any(x in s for x in ("done", "success", "completed", "finished")):
            return {"ok": True, "elapsed_s": round(time.time()-t0, 1), "raw": got}
        if any(x in s for x in ("fail", "error", "cancel")):
            return {"ok": False, "note": "graph_failed", "elapsed_s": round(time.time()-t0, 1), "raw": got}
    return {"ok": False, "note": "timeout", "elapsed_s": GRAPH_TIMEOUT_S, "raw": last}


def retrieve(ds_id: str, query: str, use_kg: bool = False) -> list[str]:
    body = {
        "question": query,
        "dataset_ids": [ds_id],
        "top_k": TOP_K,
        "similarity_threshold": 0.0,
        "vector_similarity_weight": 0.3,
    }
    if use_kg:
        body["use_kg"] = True
    got = api("POST", "/api/v1/retrieval", body)
    ranked = []
    for c in (got.get("data") or {}).get("chunks") or []:
        name = c.get("document_keyword") or c.get("docnm_kwd") or ""
        if name and name not in ranked:
            ranked.append(name)
    return ranked


def main() -> int:
    docs = load_docs()
    file_to_scan = {d["filename"]: d["id"] for d in docs}
    kb = json.loads(KB_ARTIFACT.read_text(encoding="utf-8"))
    baseline_ds = kb["dataset_id"]

    created = api("POST", "/api/v1/datasets", {
        "name": f"graph-eval-{uuid.uuid4().hex[:6]}",
        "chunk_method": "naive",
        "embedding_model": EMBEDDING_MODEL,
        "parser_config": {
            "layout_recognize": "DeepDOC",
            "chunk_token_num": 512,
            "delimiter": "\n",
            "graphrag": {"use_graphrag": True},
        },
    })
    treat_ds = (created.get("data") or {}).get("id")
    if not treat_ds:
        print("create failed", created)
        return 1
    print(f"treatment dataset={treat_ds}")

    ids = []
    for d in docs:
        up = upload(treat_ds, d["path"])
        items = up.get("data") or []
        if items:
            ids.append(items[0]["id"])
    api("POST", f"/api/v1/datasets/{treat_ds}/documents/parse", {"document_ids": ids})
    wait_parse(treat_ds, len(docs))

    print("triggering GraphRAG index...", flush=True)
    trigger = api("POST", f"/api/v1/datasets/{treat_ds}/index?type=graph", {})
    print("trigger:", json.dumps(trigger, ensure_ascii=False)[:300], flush=True)
    graph_status = wait_graph(treat_ds)

    qs = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))["questions"]
    targets = [q for q in qs
               if q["category"] in ("multi_hop", "factual")
               and (q.get("expected") or {}).get("document_ids")]

    hits = {"baseline": [], "graph": []}
    per_q = []
    for q in targets:
        relevant = q["expected"]["document_ids"]
        base_files = retrieve(baseline_ds, q["query"], use_kg=False)
        treat_files = retrieve(treat_ds, q["query"], use_kg=graph_status.get("ok", False))
        base_ranked = [file_to_scan[f] for f in base_files if f in file_to_scan]
        treat_ranked = [file_to_scan[f] for f in treat_files if f in file_to_scan]
        b_ok = hit_at_k(base_ranked, relevant, TOP_K) > 0
        t_ok = hit_at_k(treat_ranked, relevant, TOP_K) > 0
        hits["baseline"].append(b_ok)
        hits["graph"].append(t_ok)
        per_q.append({
            "id": q["id"], "query": q["query"], "relevant": relevant,
            "baseline_hit": b_ok, "graph_hit": t_ok,
            "baseline_ranked": base_ranked, "graph_ranked": treat_ranked,
        })
        print(f"  {q['id']}: base={'Y' if b_ok else '-'} graph={'Y' if t_ok else '-'}", flush=True)

    n = len(targets)
    if not graph_status.get("ok"):
        verdict = {
            "judgement": "NO_VALUE",
            "delta": 0.0, "ci_low": 0.0, "ci_high": 0.0, "n": 0,
            "threshold": DELTA_MIN,
            "reason": f"graph index failed: {graph_status.get('note')}",
        }
        status = "FAIL"
    else:
        only_base = sum(1 for b, t in zip(hits["baseline"], hits["graph"]) if b and not t)
        only_treat = sum(1 for b, t in zip(hits["baseline"], hits["graph"]) if t and not b)
        v = judge(sum(hits["baseline"]), sum(hits["graph"]), n,
                  threshold=DELTA_MIN, min_n=5, discordant=(only_base, only_treat))
        verdict = v.as_dict()
        status = "PASS" if v.judgement == "PROVEN" else "FAIL"

    report = {
        "gate": "CV-RF-05",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "status": status,
        "baseline_dataset_id": baseline_ds,
        "graph_dataset_id": treat_ds,
        "graph_trigger": trigger,
        "graph_status": {k: v for k, v in graph_status.items() if k != "raw"},
        "n_questions": n,
        "summary": {
            "baseline_hit_at_5": round(sum(hits["baseline"]) / n, 4) if n else None,
            "graph_hit_at_5": round(sum(hits["graph"]) / n, 4) if n else None,
        },
        "judgement": verdict,
        "per_question": per_q,
        "product_default": "OFF",
    }
    ARTIFACT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n===== CV-RF-05 RESULT =====")
    print(f"  graph_ok={graph_status.get('ok')} status={status}")
    print(f"  judgement={verdict.get('judgement')} delta={verdict.get('delta')}")
    print(f"written: {ARTIFACT}")
    api("DELETE", "/api/v1/datasets", {"ids": [treat_ds]})
    print("throwaway dataset deleted")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
