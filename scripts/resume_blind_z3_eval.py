"""Merge partial Z3 log verdicts with a resume eval from z3-v3-046."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
LOG = Path(r"C:\Users\User\.cursor\projects\c-Users-User-Desktop-ai-agent\terminals\935611.txt")
QUESTIONS = ROOT / "testdata" / "golden" / "z3_blind_questions.yaml"
PARTIAL = ROOT / "artifacts" / "blind_z3" / "eval_z3_partial.json"
RESUME_OUT = ROOT / "artifacts" / "blind_z3" / "eval_z3_resume.json"
FINAL = ROOT / "artifacts" / "blind_z3" / "eval_z3_run.json"


def load_partial_from_log() -> list[dict]:
    text = LOG.read_text(encoding="utf-8", errors="ignore")
    idx = text.rfind("START_EVAL")
    part = text[idx:] if idx >= 0 else text
    rows = re.findall(r"^(z3-v3-\d+)\s+\[([^\]]+)\]\s+verdict=(\w+)\s+(.*)$", part, re.M)
    by: dict[str, tuple[str, str, str]] = {}
    for qid, cat, verdict, note in rows:
        by[qid] = (cat, verdict, note.strip())
    qs = {q["id"]: q for q in yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))["questions"]}
    results = []
    for qid, (cat, verdict, note) in by.items():
        q = qs[qid]
        results.append(
            {
                "id": qid,
                "category": cat,
                "query": q["query"],
                "expected_docs": [],
                "missing_docs": [],
                "spans_expected": (q.get("expected") or {}).get("span_contains") or [],
                "spans_hit": [],
                "answer": "[prior run; answer text not captured in log]",
                "verdict": verdict,
                "note": note,
            }
        )
    return results


def main() -> int:
    partial = load_partial_from_log()
    PARTIAL.write_text(
        json.dumps(
            {
                "partial": True,
                "summary": dict(Counter(r["verdict"] for r in partial)),
                "results": partial,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print("partial", len(partial), Counter(r["verdict"] for r in partial))
    last = partial[-1]["id"] if partial else None
    print("resume_after", last)

    # resume remaining with hardened eval
    rc = subprocess.call(
        [
            sys.executable,
            str(ROOT / "scripts" / "eval_answer_correctness.py"),
            "--base",
            "http://localhost:8001",
            "--questions",
            "z3_blind_questions.yaml",
            "--resume-from",
            "z3-v3-046",
            "--out",
            str(RESUME_OUT),
        ]
    )
    if rc != 0 and not RESUME_OUT.exists():
        print("resume failed", rc)
        return rc

    resume = json.loads(RESUME_OUT.read_text(encoding="utf-8")) if RESUME_OUT.exists() else {"results": []}
    # drop overlap
    have = {r["id"] for r in partial}
    merged = partial + [r for r in resume.get("results", []) if r["id"] not in have]
    summary = {
        "total": len(merged),
        "pass": sum(1 for r in merged if r["verdict"] == "pass"),
        "fail": sum(1 for r in merged if r["verdict"] == "fail"),
        "review": sum(1 for r in merged if r["verdict"] == "review"),
        "blocked": sum(1 for r in merged if r["verdict"] == "blocked"),
    }
    FINAL.write_text(
        json.dumps(
            {
                "gate": "blind-z3-answer-correctness",
                "partial": False,
                "merged_from": ["log_partial_001_045", "resume_046_plus"],
                "summary": summary,
                "results": merged,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print("summary", summary)
    print("written", FINAL)
    return 0 if summary["total"] >= 85 else 1


if __name__ == "__main__":
    raise SystemExit(main())
