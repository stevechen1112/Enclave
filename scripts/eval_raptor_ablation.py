"""B5 / CV-RF-04 — RAPTOR hierarchical summary ablation.

Baseline: persistent enclave-golden-eval KB (DeepDOC, no RAPTOR).
Treatment: throwaway clone of the same 12 scans + POST .../index?type=raptor.

Scores multi_hop + factual questions from Z1-2 (Hit@5). RAPTOR stays OFF by
default in product flags regardless of result; this gate only decides whether
it may be enabled on approved KBs.

Writes artifacts/raptor_ablation_last_run.json.
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
ARTIFACT = ROOT / "artifacts" / "raptor_ablation_last_run.json"
TOP_K = 5
DELTA_MIN = 0.15
RAPTOR_TIMEOUT_S = 3600


def load_docs():
    docs = []
    for yml in sorted(ANNOTATION_DIR.glob("scan_*.yaml")):
        data = yaml.safe_load(yml.read_text(encoding="utf-8"))
        src = pathlib.Path(data["source_path"])
        if src.exists():
            docs.append({"id": data["id"], "path": src, "filename": data["filename"]})
    return docs


def retrieve_scans(ds_id: str, query: str, file_to_scan: dict) -> list[str]:
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


def wait_raptor(ds_id: str) -> dict:
    t0 = time.time()
    last = {}
    while time.time() - t0 < RAPTOR_TIMEOUT_S:
        time.sleep(15)
        got = api("GET", f"/api/v1/datasets/{ds_id}/index?type=raptor")
        last = got
        data = got.get("data") or got
        status = ""
        if isinstance(data, dict):
            status = str(data.get("status") or data.get("run") or data.get("progress") or "")
            # Some versions nest under tasks
            if not status and "tasks" in data:
                status = str(data["tasks"])
        print(f"  [{time.time()-t0:5.0f}s] raptor status={status!r} code={got.get('code')}", flush=True)
        s = status.lower().strip()
        # RAGFlow emits progress floats: 0..1 success path; -1 means failed.
        try:
            prog = float(s)
            if prog < 0:
                return {"ok": False, "raw": got, "elapsed_s": round(time.time() - t0, 1),
                        "note": "raptor_progress_negative"}
            if prog >= 1.0:
                return {"ok": True, "raw": got, "elapsed_s": round(time.time() - t0, 1)}
        except ValueError:
            pass
        if any(x in s for x in ("done", "success", "completed", "finished")):
            return {"ok": True, "raw": got, "elapsed_s": round(time.time() - t0, 1)}
        if any(x in s for x in ("fail", "error", "cancel")):
            return {"ok": False, "raw": got, "elapsed_s": round(time.time() - t0, 1)}
        if time.time() - t0 > 120 and got.get("code") not in (0, None, 200) and not status:
            return {"ok": False, "raw": got, "elapsed_s": round(time.time() - t0, 1),
                    "note": "raptor_status_unavailable"}
    return {"ok": False, "raw": last, "elapsed_s": RAPTOR_TIMEOUT_S, "note": "timeout"}


def main() -> int:
    docs = load_docs()
    file_to_scan = {d["filename"]: d["id"] for d in docs}
    kb = json.loads(KB_ARTIFACT.read_text(encoding="utf-8"))
    baseline_ds = kb["dataset_id"]

    # Treatment dataset
    created = api("POST", "/api/v1/datasets", {
        "name": f"raptor-eval-{uuid.uuid4().hex[:6]}",
        "chunk_method": "naive",
        "embedding_model": EMBEDDING_MODEL,
        "parser_config": {
            "layout_recognize": "DeepDOC",
            "chunk_token_num": 512,
            "delimiter": "\n",
            "raptor": {"use_raptor": True},
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

    print("triggering RAPTOR index...", flush=True)
    trigger = api("POST", f"/api/v1/datasets/{treat_ds}/index?type=raptor", {})
    print("trigger:", json.dumps(trigger, ensure_ascii=False)[:300], flush=True)
    raptor_status = wait_raptor(treat_ds)

    qs = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))["questions"]
    targets = [q for q in qs
               if q["category"] in ("multi_hop", "factual")
               and (q.get("expected") or {}).get("document_ids")]

    hits = {"baseline": [], "raptor": []}
    per_q = []
    for q in targets:
        relevant = q["expected"]["document_ids"]
        base_ranked = retrieve_scans(baseline_ds, q["query"], file_to_scan)
        treat_ranked = retrieve_scans(treat_ds, q["query"], file_to_scan)
        b_ok = hit_at_k(base_ranked, relevant, TOP_K) > 0
        t_ok = hit_at_k(treat_ranked, relevant, TOP_K) > 0
        hits["baseline"].append(b_ok)
        hits["raptor"].append(t_ok)
        per_q.append({
            "id": q["id"], "query": q["query"], "relevant": relevant,
            "baseline_ranked": base_ranked, "baseline_hit": b_ok,
            "raptor_ranked": treat_ranked, "raptor_hit": t_ok,
        })
        print(f"  {q['id']}: base={'Y' if b_ok else '-'} raptor={'Y' if t_ok else '-'}", flush=True)

    n = len(targets)
    only_base = sum(1 for b, t in zip(hits["baseline"], hits["raptor"]) if b and not t)
    only_treat = sum(1 for b, t in zip(hits["baseline"], hits["raptor"]) if t and not b)
    verdict = judge(sum(hits["baseline"]), sum(hits["raptor"]), n,
                    threshold=DELTA_MIN, min_n=5, discordant=(only_base, only_treat))

    report = {
        "gate": "CV-RF-04",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "baseline_dataset_id": baseline_ds,
        "raptor_dataset_id": treat_ds,
        "raptor_trigger": trigger,
        "raptor_status": {k: v for k, v in raptor_status.items() if k != "raw"},
        "raptor_raw_status_code": (raptor_status.get("raw") or {}).get("code"),
        "n_questions": n,
        "summary": {
            "baseline_hit_at_5": round(sum(hits["baseline"]) / n, 4) if n else 0,
            "raptor_hit_at_5": round(sum(hits["raptor"]) / n, 4) if n else 0,
        },
        "judgement": verdict.as_dict(),
        "per_question": per_q,
        "product_default": "OFF",  # RAPTOR remains opt-in regardless
    }
    ARTIFACT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n===== B5 RAPTOR RESULT =====")
    print(f"  baseline hit@5={report['summary']['baseline_hit_at_5']:.1%}")
    print(f"  raptor   hit@5={report['summary']['raptor_hit_at_5']:.1%}")
    print(f"  judgement={verdict.judgement} delta={verdict.delta:+.1%} ci_low={verdict.ci_low:+.3f}")
    print(f"  raptor_ok={raptor_status.get('ok')} elapsed={raptor_status.get('elapsed_s')}")
    print(f"written: {ARTIFACT}")

    api("DELETE", "/api/v1/datasets", {"ids": [treat_ds]})
    print("throwaway raptor dataset deleted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
