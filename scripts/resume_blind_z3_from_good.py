"""Merge good Blind Z3 results and resume from first ERROR id."""
from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "artifacts" / "blind_z3"
GOOD058 = BASE / "eval_z3_good_001_058.json"
RESUME059 = BASE / "eval_z3_resume_059.json"
GOOD_THRU = BASE / "eval_z3_good_thru.json"
RESUME_OUT = BASE / "eval_z3_tail.json"
FINAL = BASE / "eval_z3_run.json"
BASE_URL = "http://localhost:8011"


def is_infra_error(note: str) -> bool:
    n = note or ""
    return "ERROR" in n and any(
        x in n for x in ("ConnectError", "ReadError", "ReadTimeout", "404", "10054", "10061")
    )


def main() -> int:
    good = json.loads(GOOD058.read_text(encoding="utf-8"))["results"]
    if RESUME059.exists():
        for r in json.loads(RESUME059.read_text(encoding="utf-8")).get("results", []):
            if not is_infra_error(r.get("note") or ""):
                # replace or append by id
                good = [x for x in good if x["id"] != r["id"]] + [r]
    good.sort(key=lambda r: r["id"])
    last = good[-1]["id"]
    # next id after last
    n = int(last.split("-")[-1]) + 1
    resume_from = f"z3-v3-{n:03d}"
    GOOD_THRU.write_text(
        json.dumps(
            {"partial": True, "summary": dict(Counter(r["verdict"] for r in good)), "results": good},
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print("good_thru", len(good), Counter(r["verdict"] for r in good), "resume_from", resume_from)

    rc = subprocess.call(
        [
            sys.executable,
            "-u",
            str(ROOT / "scripts" / "eval_answer_correctness.py"),
            "--base",
            BASE_URL,
            "--questions",
            "z3_blind_questions.yaml",
            "--resume-from",
            resume_from,
            "--out",
            str(RESUME_OUT),
        ]
    )
    if not RESUME_OUT.exists():
        print("tail missing", rc)
        return rc or 1

    tail = json.loads(RESUME_OUT.read_text(encoding="utf-8"))
    have = {r["id"] for r in good}
    # drop infra errors from merge; keep real answers
    merged = good[:]
    for r in tail.get("results", []):
        if r["id"] in have:
            continue
        if is_infra_error(r.get("note") or ""):
            print("skip_infra", r["id"], (r.get("note") or "")[:60])
            continue
        merged.append(r)

    by_type: dict[str, Counter] = {}
    for r in merged:
        t = (r.get("category") or "").replace("blind_z3_", "") or "?"
        by_type.setdefault(t, Counter())[r["verdict"]] += 1
    summary = {
        "total": len(merged),
        "pass": sum(1 for r in merged if r["verdict"] == "pass"),
        "fail": sum(1 for r in merged if r["verdict"] == "fail"),
        "review": sum(1 for r in merged if r["verdict"] == "review"),
        "blocked": sum(1 for r in merged if r["verdict"] == "blocked"),
        "incomplete": 85 - len(merged),
    }
    FINAL.write_text(
        json.dumps(
            {
                "gate": "blind-z3-answer-correctness",
                "partial": summary["incomplete"] > 0,
                "summary": summary,
                "by_type": {k: dict(v) for k, v in sorted(by_type.items())},
                "results": merged,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print("summary", summary)
    print("by_type", {k: dict(v) for k, v in sorted(by_type.items())})
    print("written", FINAL)
    return 0 if summary["incomplete"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
