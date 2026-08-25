"""VISION Phase 4 — 對抗集閘門。

Usage:
  python scripts/eval_adversarial_gate.py [--base http://localhost:8001]
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
import time
import unicodedata

import httpx
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
QUESTIONS = ROOT / "testdata" / "golden" / "z1_adversarial_questions.yaml"
OUT = ROOT / "artifacts" / "adversarial_last_run.json"
REFUSAL_MARKERS = ["無法", "沒有", "找不到", "未收錄", "無從", "不包含", "並未", "沒有提到", "無相關", "拒絕", "不足以"]


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").casefold()
    return re.sub(r"\s+", "", s)


def span_in(span: str, answer: str) -> bool:
    # 與 answer_correctness 共用同一套 span 正規化，避免兩套標準漂移
    from eval_answer_correctness import span_in_answer

    return span_in_answer(span, answer)


def login(client: httpx.Client) -> None:
    r = client.post(
        "/api/v1/auth/login/access-token",
        data={
            "username": os.environ["EVAL_ADMIN_EMAIL"],
            "password": os.environ["EVAL_ADMIN_PASSWORD"],
        },
    )
    r.raise_for_status()
    client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"


def stream_answer(client: httpx.Client, question: str) -> str:
    parts = []
    with client.stream(
        "POST",
        "/api/v1/chat/chat/stream",
        json={"question": question},
        headers={"Accept": "text/event-stream"},
        timeout=180,
    ) as resp:
        resp.raise_for_status()
        for raw in resp.iter_lines():
            if not raw:
                continue
            line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                d = json.loads(data)
            except json.JSONDecodeError:
                continue
            if d.get("type") == "token" and "content" in d:
                parts.append(d["content"])
    return "".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8001")
    args = ap.parse_args()
    questions = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))["questions"]
    t0 = time.time()
    cases = []
    with httpx.Client(base_url=args.base, timeout=180.0) as client:
        login(client)
        for q in questions:
            exp = q["expected"]
            answer = stream_answer(client, q["query"])
            viol = []
            if exp.get("must_refuse"):
                if not any(m in answer for m in REFUSAL_MARKERS):
                    viol.append("expected_refusal_missing")
            for s in exp.get("span_contains") or []:
                if not span_in(s, answer):
                    viol.append(f"span_missing:{s}")
            for s in exp.get("must_not_contain") or []:
                if span_in(s, answer):
                    viol.append(f"forbidden_span_present:{s}")
            verdict = "fail" if viol else "pass"
            cases.append({
                "id": q["id"],
                "trap": q.get("trap"),
                "query": q["query"],
                "verdict": verdict,
                "violations": viol,
                "answer_excerpt": answer[:400],
            })
            print(q["id"], verdict, viol or "ok")

    summary = {
        "total": len(cases),
        "pass": sum(1 for c in cases if c["verdict"] == "pass"),
        "fail": sum(1 for c in cases if c["verdict"] == "fail"),
    }
    status = "PASS" if summary["fail"] == 0 else "FAIL"
    report = {
        "gate": "VISION-ADV",
        "schema_version": 1,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "status": status,
        "summary": summary,
        "elapsed_s": round(time.time() - t0, 1),
        "cases": cases,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("status:", status, summary)
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
