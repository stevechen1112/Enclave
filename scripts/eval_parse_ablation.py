"""B3 / CV-RF-01b: real-scan parse ablation against Z1-1 field annotations.

Runs Plain Text vs DeepDOC over the annotated real scanned PDFs and scores each
arm against the human ground truth in testdata/golden/z1_scan_annotations/*.yaml:

  - field hit rate: normalized expected value found verbatim in extracted text
  - field CER: best-window CER around the longest common block (0 for hits)
  - paired McNemar judgement on per-field hits (baseline=Plain Text)

Gate PASS requires: judgement PROVEN and DeepDOC mean field CER <= threshold.

Usage:
  RAGFLOW_API_KEY=... python scripts/eval_parse_ablation.py [--limit N] [--keep]
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import pathlib
import sys
import time

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from app.eval import character_error_rate, judge, normalize_field, normalize_field_t2s  # noqa: E402
from eval_coverage import run_arm  # noqa: E402
ANNOTATION_DIR = ROOT / "testdata" / "golden" / "z1_scan_annotations"
ARTIFACT = ROOT / "artifacts" / "parse_ablation_last_run.json"

CER_MAX = float(os.getenv("CV_RF01B_CER_MAX", "0.35"))
DELTA_MIN = float(os.getenv("CV_RF01B_DELTA_MIN", "0.20"))


def load_annotations() -> list[dict]:
    docs = []
    for yml in sorted(ANNOTATION_DIR.glob("scan_*.yaml")):
        data = yaml.safe_load(yml.read_text(encoding="utf-8"))
        fields = [f for f in (data.get("fields") or []) if f.get("expected")]
        if not fields:
            continue
        src = pathlib.Path(data["source_path"])
        if not src.exists():
            print(f"  WARN missing source: {src}")
            continue
        docs.append({"id": data["id"], "path": src, "fields": fields})
    return docs


def best_window_cer(expected: str, text: str, norm=normalize_field) -> float:
    """CER of expected against the most similar region of text (0 if contained)."""
    ref = norm(expected)
    hyp = norm(text)
    if not ref:
        return 0.0
    if not hyp:
        return 1.0
    if ref in hyp:
        return 0.0
    match = difflib.SequenceMatcher(None, ref, hyp, autojunk=False).find_longest_match(
        0, len(ref), 0, len(hyp)
    )
    if match.size == 0:
        return 1.0
    # Centre a ref-length window on the longest common block.
    centre = match.b + match.size // 2
    start = max(0, min(centre - len(ref) // 2, len(hyp) - len(ref)))
    window = hyp[start:start + len(ref)]
    return character_error_rate(ref, window, normalize=False)


def score_arm(per_doc: dict, docs: list[dict]) -> dict:
    """Return per-field hits/CERs plus aggregate rates for one arm.

    Each field is scored twice: `strict` (verbatim after normalize_field) and
    `t2s` (script-tolerant, simplified->traditional applied to both sides).
    DeepDOC's OCR emits simplified characters for traditional scans; the gate
    judges on t2s but the strict numbers are disclosed in the artifact.
    """
    per_field = []
    for doc in docs:
        text = (per_doc.get(doc["id"]) or {}).get("text", "")
        for f in doc["fields"]:
            expected = f["expected"]
            hit_strict = normalize_field(expected) in normalize_field(text)
            hit_t2s = normalize_field_t2s(expected) in normalize_field_t2s(text)
            cer_strict = 0.0 if hit_strict else best_window_cer(expected, text, normalize_field)
            cer_t2s = 0.0 if hit_t2s else best_window_cer(expected, text, normalize_field_t2s)
            per_field.append({
                "doc": doc["id"],
                "name": f.get("name", ""),
                "expected": expected,
                "page": f.get("page"),
                "hit": hit_t2s,
                "cer": round(cer_t2s, 4),
                "hit_strict": hit_strict,
                "cer_strict": round(cer_strict, 4),
            })
    n = len(per_field)
    hits = sum(1 for r in per_field if r["hit"])
    hits_strict = sum(1 for r in per_field if r["hit_strict"])
    return {
        "per_field": per_field,
        "fields": n,
        "hits": hits,
        "hit_rate": round(hits / n, 4) if n else 0.0,
        "mean_cer": round(sum(r["cer"] for r in per_field) / n, 4) if n else 1.0,
        "hits_strict": hits_strict,
        "hit_rate_strict": round(hits_strict / n, 4) if n else 0.0,
        "mean_cer_strict": round(sum(r["cer_strict"] for r in per_field) / n, 4) if n else 1.0,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    docs = load_annotations()
    if args.limit:
        docs = docs[: args.limit]
    if not docs:
        print("no annotated documents found")
        return 1
    total_fields = sum(len(d["fields"]) for d in docs)
    print(f"annotated docs={len(docs)} fields={total_fields}")

    files = [(d["id"], d["path"]) for d in docs]
    arms = {}
    for layout in ("Plain Text", "DeepDOC"):
        print(f"\n=== arm {layout} ===", flush=True)
        arms[layout] = run_arm(layout, files)

    scored = {layout: score_arm(arm["per_doc"], docs) for layout, arm in arms.items()}

    base = scored["Plain Text"]
    treat = scored["DeepDOC"]
    only_base = sum(1 for b, t in zip(base["per_field"], treat["per_field"]) if b["hit"] and not t["hit"])
    only_treat = sum(1 for b, t in zip(base["per_field"], treat["per_field"]) if t["hit"] and not b["hit"])
    verdict = judge(base["hits"], treat["hits"], total_fields,
                    threshold=DELTA_MIN, discordant=(only_base, only_treat))

    gate_pass = verdict.judgement == "PROVEN" and treat["mean_cer"] <= CER_MAX

    report = {
        "gate": "CV-RF-01b",
        "status": "PASS" if gate_pass else "FAIL",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "corpus": "real_scan_annotated",
        "golden_tier": 1,
        "n_docs": len(docs),
        "n_fields": total_fields,
        "thresholds": {"mean_cer_max": CER_MAX, "hit_rate_delta_min": DELTA_MIN},
        "summary": {
            layout: {"hits": s["hits"], "fields": s["fields"],
                     "hit_rate": s["hit_rate"], "mean_cer": s["mean_cer"],
                     "hit_rate_strict": s["hit_rate_strict"],
                     "mean_cer_strict": s["mean_cer_strict"],
                     "elapsed_s": arms[layout]["elapsed_s"]}
            for layout, s in scored.items()
        },
        "hit_judgement": verdict.as_dict(),
        "per_field": {layout: s["per_field"] for layout, s in scored.items()},
        "datasets": {layout: arm["dataset_id"] for layout, arm in arms.items()},
    }
    ARTIFACT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    print("\n===== RESULT =====")
    for layout, s in scored.items():
        print(f"  {layout:11s} hit_rate(t2s)={s['hit_rate']:.1%} ({s['hits']}/{s['fields']}) "
              f"cer(t2s)={s['mean_cer']} | strict hit={s['hit_rate_strict']:.1%} "
              f"cer={s['mean_cer_strict']} | elapsed={arms[layout]['elapsed_s']}s")
    print(f"  hit judgement = {verdict.judgement} (delta={verdict.delta:+.1%}, "
          f"CI low={verdict.ci_low:+.3f}, mcnemar_p={verdict.detail.get('mcnemar_p')})")
    print(f"  gate status = {report['status']}")
    print(f"written: {ARTIFACT}")

    if not args.keep:
        from eval_coverage import api
        for arm in arms.values():
            api("DELETE", "/api/v1/datasets", {"ids": [arm["dataset_id"]]})
        print("throwaway datasets deleted")
    return 0 if gate_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
