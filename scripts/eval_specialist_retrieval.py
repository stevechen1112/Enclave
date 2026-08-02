"""B6 / CV-RF-06 — specialist retrieval gate (latency + flag discipline).

Does NOT enable RAGFLOW_SPECIALIST_ENABLED. Measures RAGFlow retrieval latency
on the Z1-2 set against enclave-golden-eval and records whether the product
gate is still correctly OFF.

PASS criteria (all required):
  1. specialist_retrieval_enabled() is False under current env
  2. p95 latency of 20 retrieval calls ≤ SPECIALIST_P95_MS (default 3000)
  3. answerable Hit@5 ≥ 0.80 (reuses E1 scoring against expected docs)

Writes artifacts/specialist_retrieval_last_run.json.
"""
from __future__ import annotations

import json
import os
import pathlib
import statistics
import sys
import time

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from app.eval import hit_at_k  # noqa: E402
from app.services.specialist_gate import specialist_retrieval_enabled  # noqa: E402
from eval_coverage import api  # noqa: E402

QUESTIONS = ROOT / "testdata" / "golden" / "z1_retrieve_questions.yaml"
ANNOTATION_DIR = ROOT / "testdata" / "golden" / "z1_scan_annotations"
KB_ARTIFACT = ROOT / "artifacts" / "golden_eval_kb.json"
ARTIFACT = ROOT / "artifacts" / "specialist_retrieval_last_run.json"
TOP_K = 5
P95_MS = float(os.getenv("SPECIALIST_P95_MS", "3000"))
HIT_MIN = float(os.getenv("SPECIALIST_HIT_MIN", "0.80"))


def main() -> int:
    kb = json.loads(KB_ARTIFACT.read_text(encoding="utf-8"))
    ds_id = kb["dataset_id"]
    file_to_scan = {}
    for yml in sorted(ANNOTATION_DIR.glob("scan_*.yaml")):
        data = yaml.safe_load(yml.read_text(encoding="utf-8"))
        file_to_scan[data["filename"]] = data["id"]

    qs = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))["questions"]
    latencies = []
    per_q = []
    answerable_hits = []
    for q in qs:
        t0 = time.perf_counter()
        got = api("POST", "/api/v1/retrieval", {
            "question": q["query"],
            "dataset_ids": [ds_id],
            "top_k": TOP_K,
            "similarity_threshold": 0.0,
            "vector_similarity_weight": 0.3,
        })
        ms = (time.perf_counter() - t0) * 1000
        latencies.append(ms)
        ranked = []
        for c in (got.get("data") or {}).get("chunks") or []:
            name = c.get("document_keyword") or c.get("docnm_kwd") or ""
            scan = file_to_scan.get(name)
            if scan and scan not in ranked:
                ranked.append(scan)
        exp = q.get("expected") or {}
        relevant = exp.get("document_ids") or []
        must_refuse = bool(exp.get("must_refuse"))
        if must_refuse:
            ok = len(ranked) == 0
        else:
            ok = hit_at_k(ranked, relevant, TOP_K) > 0
            answerable_hits.append(ok)
        per_q.append({
            "id": q["id"], "category": q["category"], "latency_ms": round(ms, 1),
            "ranked": ranked, "ok": ok,
        })
        print(f"  {q['id']} {ms:7.1f}ms ok={ok}", flush=True)

    lat_sorted = sorted(latencies)
    p95 = lat_sorted[max(0, int(round(0.95 * (len(lat_sorted) - 1))))]
    ans_rate = (sum(answerable_hits) / len(answerable_hits)) if answerable_hits else 0.0
    flag_off = specialist_retrieval_enabled() is False

    checks = {
        "flag_default_off": flag_off,
        "p95_within_budget": p95 <= P95_MS,
        "answerable_hit_at_5_ok": ans_rate >= HIT_MIN,
    }
    status = "PASS" if all(checks.values()) else "FAIL"

    report = {
        "gate": "CV-RF-06",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "status": status,
        "checks": checks,
        "thresholds": {"p95_ms_max": P95_MS, "answerable_hit_min": HIT_MIN},
        "latency_ms": {
            "n": len(latencies),
            "mean": round(statistics.mean(latencies), 1),
            "p50": round(statistics.median(latencies), 1),
            "p95": round(p95, 1),
            "max": round(max(latencies), 1),
        },
        "answerable_hit_at_5": round(ans_rate, 4),
        "specialist_enabled_now": specialist_retrieval_enabled(),
        "admit_to_fanout": False,  # E2: still OFF — refusal gap remains
        "per_question": per_q,
    }
    ARTIFACT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n===== B6 SPECIALIST RESULT =====")
    print(f"  flag_off={flag_off} p95={p95:.0f}ms (budget {P95_MS:.0f}) "
          f"answerable_hit={ans_rate:.0%} status={status}")
    print(f"  admit_to_fanout=False (E2 refusal gap)")
    print(f"written: {ARTIFACT}")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
