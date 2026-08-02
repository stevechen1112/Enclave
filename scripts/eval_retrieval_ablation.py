"""E1 — retrieval ablation matrix: canonical vs +RAGFlow (vs +WeKnora / +PipesHub).

Runs the Z1-2 G-RETRIEVE Tier-1 question set (20 questions) against each
retrieval arm and scores Hit@K / MRR / nDCG@K per question against the
expected scan documents, then applies the paired McNemar judgement.

Arms:
  canonical  Enclave pgvector KB (KnowledgeBaseRetriever). The 12 golden scans
             were never ingested here — this is the honest "before" baseline.
  ragflow    RAGFlow retrieval API on the persistent enclave-golden-eval KB
             (built by scripts/build_golden_eval_kb.py).

Unanswerable questions are scored as a retrieval-level refusal proxy: success
means no chunk returned at/above the arm's score threshold.

Usage:
  python scripts/eval_retrieval_ablation.py --arms canonical,ragflow
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from app.eval import hit_at_k, judge, mean_reciprocal_rank, ndcg_at_k  # noqa: E402
from eval_coverage import api  # noqa: E402  (RAGFlow HTTP helper)

GOLDEN = ROOT / "testdata" / "golden"
QUESTIONS = GOLDEN / "z1_retrieve_questions.yaml"
ANNOTATION_DIR = GOLDEN / "z1_scan_annotations"
KB_ARTIFACT = ROOT / "artifacts" / "golden_eval_kb.json"
ARTIFACT = ROOT / "artifacts" / "retrieval_ablation_last_run.json"

TOP_K = 5
SCORE_THRESHOLD = float(os.getenv("E1_SCORE_THRESHOLD", "0.2"))
DELTA_MIN = float(os.getenv("E1_DELTA_MIN", "0.20"))


def load_scan_filename_map() -> dict[str, str]:
    """scan_id -> original golden filename (as uploaded to RAGFlow)."""
    out = {}
    for yml in sorted(ANNOTATION_DIR.glob("scan_*.yaml")):
        data = yaml.safe_load(yml.read_text(encoding="utf-8"))
        out[data["id"]] = data["filename"]
    return out


def arm_canonical(query: str) -> list[dict]:
    """Enclave pgvector canonical search. Returns [{document_id, score}]."""
    from app.db.session import SessionLocal
    from app.models.document import Document
    from app.services.kb_retrieval import KnowledgeBaseRetriever

    db = SessionLocal()
    try:
        tenant = db.query(Document.tenant_id).first()
        if not tenant:
            return []
        raw = KnowledgeBaseRetriever().search(
            tenant_id=tenant[0], query=query, top_k=TOP_K,
            mode="hybrid", min_score=0.0, rerank=False, use_cache=False,
        )
        return [
            {"document_id": str(r.get("document_id") or ""),
             "filename": (r.get("metadata") or {}).get("filename", ""),
             "score": float(r.get("score") or 0.0)}
            for r in raw
        ]
    finally:
        db.close()


def arm_ragflow(query: str, dataset_id: str) -> list[dict]:
    got = api("POST", "/api/v1/retrieval", {
        "question": query,
        "dataset_ids": [dataset_id],
        "top_k": TOP_K,
        "similarity_threshold": 0.0,
        "vector_similarity_weight": 0.3,
    })
    chunks = (got.get("data") or {}).get("chunks") or []
    return [
        {"document_id": c.get("document_id") or c.get("doc_id") or "",
         "filename": c.get("document_keyword") or c.get("docnm_kwd") or "",
         "score": float(c.get("similarity") or 0.0)}
        for c in chunks
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", default="canonical,ragflow")
    args = ap.parse_args()
    arm_names = [a.strip() for a in args.arms.split(",") if a.strip()]

    spec = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))
    questions = spec["questions"]
    scan_to_file = load_scan_filename_map()
    file_to_scan = {v: k for k, v in scan_to_file.items()}

    rf_dataset_id = None
    rf_doc_to_name = {}
    if "ragflow" in arm_names:
        kb = json.loads(KB_ARTIFACT.read_text(encoding="utf-8"))
        rf_dataset_id = kb["dataset_id"]
        rf_doc_to_name = {did: d["name"] for did, d in kb["documents"].items()}

    def to_scan_ids(hits: list[dict]) -> list[str]:
        ids = []
        for h in hits:
            name = h.get("filename") or rf_doc_to_name.get(h["document_id"], "")
            scan = file_to_scan.get(name)
            if scan and scan not in ids:
                ids.append(scan)
        return ids

    per_question = []
    arm_hits: dict[str, list[bool]] = {a: [] for a in arm_names}
    arm_scores: dict[str, dict[str, float]] = {
        a: {"hit": 0.0, "mrr": 0.0, "ndcg": 0.0} for a in arm_names
    }

    for q in questions:
        qid, query = q["id"], q["query"]
        exp = q.get("expected") or {}
        relevant = exp.get("document_ids") or []
        must_refuse = bool(exp.get("must_refuse"))
        row = {"id": qid, "category": q["category"], "query": query}

        for arm in arm_names:
            if arm == "canonical":
                hits = arm_canonical(query)
            elif arm == "ragflow":
                hits = arm_ragflow(query, rf_dataset_id)
            else:
                raise ValueError(f"unknown arm {arm}")

            ranked = to_scan_ids([h for h in hits if h["score"] >= SCORE_THRESHOLD])
            if must_refuse:
                # refusal proxy: nothing retrieved above threshold
                ok = len(ranked) == 0
                row[f"{arm}_refused"] = ok
                row[f"{arm}_top_score"] = round(max((h["score"] for h in hits), default=0.0), 4)
            else:
                ok = hit_at_k(ranked, relevant, TOP_K) > 0
                row[f"{arm}_ranked"] = ranked
                row[f"{arm}_hit"] = ok
                arm_scores[arm]["mrr"] += mean_reciprocal_rank(ranked, relevant)
                arm_scores[arm]["ndcg"] += ndcg_at_k(ranked, relevant, TOP_K)
            arm_hits[arm].append(ok)
            arm_scores[arm]["hit"] += 1.0 if ok else 0.0
        per_question.append(row)
        print(f"  {qid} [{q['category']}] " +
              " ".join(f"{a}={'Y' if arm_hits[a][-1] else '-'}" for a in arm_names), flush=True)

    n = len(questions)
    summary = {}
    for arm in arm_names:
        summary[arm] = {
            "hit_at_5": round(arm_scores[arm]["hit"] / n, 4),
            "mrr": round(arm_scores[arm]["mrr"] / n, 4),
            "ndcg_at_5": round(arm_scores[arm]["ndcg"] / n, 4),
        }

    judgements = {}
    if "canonical" in arm_names:
        base = arm_hits["canonical"]
        for arm in arm_names:
            if arm == "canonical":
                continue
            treat = arm_hits[arm]
            only_base = sum(1 for b, t in zip(base, treat) if b and not t)
            only_treat = sum(1 for b, t in zip(base, treat) if t and not b)
            v = judge(sum(base), sum(treat), n, threshold=DELTA_MIN,
                      min_n=10, discordant=(only_base, only_treat))
            judgements[f"canonical_vs_{arm}"] = v.as_dict()

    report = {
        "gate": "E1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "question_set": "z1_retrieve_questions.yaml",
        "n_questions": n,
        "top_k": TOP_K,
        "score_threshold": SCORE_THRESHOLD,
        "arms": arm_names,
        "summary": summary,
        "judgements": judgements,
        "per_question": per_question,
    }
    ARTIFACT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    print("\n===== E1 RESULT =====")
    for arm, s in summary.items():
        print(f"  {arm:10s} hit@5={s['hit_at_5']:.1%} mrr={s['mrr']:.3f} ndcg@5={s['ndcg_at_5']:.3f}")
    for name, j in judgements.items():
        print(f"  {name}: {j['judgement']} (delta={j['delta']:+.1%}, ci_low={j['ci_low']:+.3f}, "
              f"p={j.get('mcnemar_p')})")
    print(f"written: {ARTIFACT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
