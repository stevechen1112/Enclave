"""D4 / CV-WK-04 (RAGFlow arm) — parent-child chunking ablation.

Ownership decision (plan §WK-04): when parsing already goes through RAGFlow,
enable parent_child on RAGFlow — do NOT also enable WeKnora parent-child.

Arms (same 12 golden scans, same DeepDOC layout):
  naive         parser_config without parent_child
  parent_child  parser_config.parent_child.use_parent_child=true

Scores:
  - child/parent chunk structure present (parent_child arm only)
  - Hit@5 on G-PARENT-style questions (long-doc detail lookup from Z1-2
    factual + table_lookup subset) via RAGFlow retrieval

Writes artifacts/parent_child_ablation_last_run.json.
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
from eval_coverage import api, upload, all_chunk_text, EMBEDDING_MODEL  # noqa: E402

ANNOTATION_DIR = ROOT / "testdata" / "golden" / "z1_scan_annotations"
QUESTIONS = ROOT / "testdata" / "golden" / "z1_retrieve_questions.yaml"
ARTIFACT = ROOT / "artifacts" / "parent_child_ablation_last_run.json"
DELTA_MIN = 0.10
TOP_K = 5


def load_docs():
    docs = []
    for yml in sorted(ANNOTATION_DIR.glob("scan_*.yaml")):
        data = yaml.safe_load(yml.read_text(encoding="utf-8"))
        src = pathlib.Path(data["source_path"])
        if src.exists():
            docs.append({"id": data["id"], "path": src, "filename": data["filename"]})
    return docs


def run_arm(name: str, parent_child: bool, docs: list) -> dict:
    ds_name = f"pc-{name}-{uuid.uuid4().hex[:6]}"
    parser_config = {
        "layout_recognize": "DeepDOC",
        "chunk_token_num": 512,
        "delimiter": "\n",
    }
    if parent_child:
        parser_config["parent_child"] = {
            "use_parent_child": True,
            "children_delimiter": "\n\n",
        }
    created = api("POST", "/api/v1/datasets", {
        "name": ds_name,
        "chunk_method": "naive",
        "embedding_model": EMBEDDING_MODEL,
        "parser_config": parser_config,
    })
    ds_id = (created.get("data") or {}).get("id")
    if not ds_id:
        raise RuntimeError(f"dataset create failed: {created}")
    print(f"  dataset={ds_id} parent_child={parent_child}", flush=True)

    name_to_docid = {}
    scan_to_rf = {}
    for d in docs:
        up = upload(ds_id, d["path"])
        items = up.get("data") or []
        if items:
            name_to_docid[d["filename"]] = items[0]["id"]
            scan_to_rf[d["id"]] = items[0]["id"]

    api("POST", f"/api/v1/datasets/{ds_id}/documents/parse",
        {"document_ids": list(name_to_docid.values())})

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
        print(f"  [{time.time()-t0:5.0f}s] {name}: {len(rows)-len(pending)}/{len(rows)}", flush=True)
        if not pending:
            time.sleep(15)
            break

    # Structure probe: any chunk that carries a parent_id / available hierarchy
    struct = {"docs_with_chunks": 0, "total_chunks": 0, "chunks_with_parent_hint": 0}
    for scan_id, rf_id in scan_to_rf.items():
        got = api("GET", f"/api/v1/datasets/{ds_id}/documents/{rf_id}/chunks?page=1&page_size=100")
        chunks = ((got.get("data") or {}).get("chunks") or [])
        if chunks:
            struct["docs_with_chunks"] += 1
        struct["total_chunks"] += len(chunks)
        for c in chunks:
            if c.get("parent_id") or c.get("available") is False or "parent" in str(c.get("doc_type", "")).lower():
                struct["chunks_with_parent_hint"] += 1

    return {
        "dataset_id": ds_id,
        "scan_to_rf": scan_to_rf,
        "name_to_docid": name_to_docid,
        "structure": struct,
        "elapsed_s": round(time.time() - t0, 1),
        "doc_stats": {d.get("name"): {"run": d.get("run"), "chunks": d.get("chunk_count")}
                      for d in rows.values()},
    }


def retrieve(ds_id: str, query: str) -> list[str]:
    """Return ranked scan filenames from RAGFlow retrieval."""
    got = api("POST", "/api/v1/retrieval", {
        "question": query,
        "dataset_ids": [ds_id],
        "top_k": TOP_K,
        "similarity_threshold": 0.0,
        "vector_similarity_weight": 0.3,
    })
    chunks = (got.get("data") or {}).get("chunks") or []
    ranked = []
    for c in chunks:
        name = c.get("document_keyword") or c.get("docnm_kwd") or ""
        if name and name not in ranked:
            ranked.append(name)
    return ranked


def main() -> int:
    docs = load_docs()
    print(f"docs={len(docs)}")
    file_to_scan = {d["filename"]: d["id"] for d in docs}

    arms = {
        "naive": run_arm("naive", False, docs),
        "parent_child": run_arm("parent_child", True, docs),
    }

    # Score on factual + table_lookup questions that have expected docs
    qs = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))["questions"]
    targets = [q for q in qs
               if q["category"] in ("factual", "table_lookup")
               and (q.get("expected") or {}).get("document_ids")]

    per_q = []
    hits = {a: [] for a in arms}
    for q in targets:
        relevant = q["expected"]["document_ids"]
        row = {"id": q["id"], "query": q["query"], "relevant": relevant}
        for arm, meta in arms.items():
            ranked_files = retrieve(meta["dataset_id"], q["query"])
            ranked_scans = [file_to_scan[f] for f in ranked_files if f in file_to_scan]
            ok = hit_at_k(ranked_scans, relevant, TOP_K) > 0
            hits[arm].append(ok)
            row[f"{arm}_ranked"] = ranked_scans
            row[f"{arm}_hit"] = ok
        per_q.append(row)
        print(f"  {q['id']}: naive={'Y' if hits['naive'][-1] else '-'} "
              f"pc={'Y' if hits['parent_child'][-1] else '-'}", flush=True)

    n = len(targets)
    only_base = sum(1 for b, t in zip(hits["naive"], hits["parent_child"]) if b and not t)
    only_treat = sum(1 for b, t in zip(hits["naive"], hits["parent_child"]) if t and not b)
    verdict = judge(sum(hits["naive"]), sum(hits["parent_child"]), n,
                    threshold=DELTA_MIN, min_n=5, discordant=(only_base, only_treat))

    report = {
        "gate": "CV-WK-04",
        "ownership": "ragflow_parent_child",  # WeKnora parent-child intentionally OFF
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "n_docs": len(docs),
        "n_questions": n,
        "structure": {a: arms[a]["structure"] for a in arms},
        "summary": {
            a: {"hit_at_5": round(sum(hits[a]) / n, 4) if n else 0.0,
                "elapsed_s": arms[a]["elapsed_s"]}
            for a in arms
        },
        "judgement": verdict.as_dict(),
        "per_question": per_q,
        "datasets": {a: arms[a]["dataset_id"] for a in arms},
    }
    ARTIFACT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    print("\n===== D4 RESULT =====")
    for a in arms:
        print(f"  {a:13s} hit@5={report['summary'][a]['hit_at_5']:.1%} "
              f"chunks={arms[a]['structure']['total_chunks']} "
              f"parent_hints={arms[a]['structure']['chunks_with_parent_hint']}")
    print(f"  judgement={verdict.judgement} delta={verdict.delta:+.1%} ci_low={verdict.ci_low:+.3f}")
    print(f"written: {ARTIFACT}")

    for arm in arms.values():
        api("DELETE", "/api/v1/datasets", {"ids": [arm["dataset_id"]]})
    print("throwaway datasets deleted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
