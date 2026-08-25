"""Answer-correctness acceptance — Z1-2 golden questions against the LIVE stack.

Unlike E1 (retrieval Hit@5) and P3 (keyword overlap), this judges the actual
generated answer against human-annotated ground truth from the source
documents (z1_scan_annotations). Three verdict types:

- span_contains questions: ground-truth values must appear in the ANSWER TEXT
  (answer-level factual correctness, not just retrieval).
- unanswerable questions: the system must refuse rather than fabricate.
- questions without transcribed ground truth: answer + citations recorded for
  human/agent review (verdict=review).

Usage:
  python scripts/eval_answer_correctness.py [--base http://localhost:8001]
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
QUESTIONS = ROOT / "testdata" / "golden" / "z1_retrieve_questions.yaml"
EXPANDED = ROOT / "testdata" / "golden" / "z1_expanded_from_annotations.yaml"
MANIFEST = ROOT / "testdata" / "golden" / "z1_scan_annotations" / "manifest.json"
OUT = ROOT / "artifacts" / "answer_correctness_last_run.json"

REFUSAL_MARKERS = ["無法", "沒有", "找不到", "未收錄", "無從", "不包含", "並未", "沒有提到", "無相關"]


def _normalize_span_text(s: str) -> str:
    """Collapse whitespace / dash variants and casefold for span matching.

    Prevents false FAIL on answers that are factually correct but use
    en-dash vs hyphen, spaced year labels, or KiGo vs KiGO casing.
    """
    s = unicodedata.normalize("NFKC", s or "")
    s = s.casefold()
    for ch in ("\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2212", "－", "〜", "~"):
        s = s.replace(ch, "-")
    s = re.sub(r"\s+", "", s)
    # 日期正規化（保留年月日字元、補零），讓 2026-02-02 與 2026年2月2日 對齊，
    # 且不破壞「11月15」這類部分日期的子串匹配
    s = re.sub(
        r"(\d{3,4})年(\d{1,2})月(\d{1,2})日",
        lambda m: f"{m.group(1)}年{int(m.group(2)):02d}月{int(m.group(3)):02d}日",
        s,
    )
    s = re.sub(
        r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})",
        lambda m: f"{m.group(1)}年{int(m.group(2)):02d}月{int(m.group(3)):02d}日",
        s,
    )
    # 期間範圍（114年09-10月 / 114年9－10月 / 114年7月至8月）→ 補零合併
    s = re.sub(
        r"(\d{3,4})年(\d{1,2})月?[-–—－~〜至到](\d{1,2})月",
        lambda m: f"{m.group(1)}年{int(m.group(2)):02d}{int(m.group(3)):02d}月",
        s,
    )
    # 常見正字法變體折疊（計畫≡計劃、臺≡台）
    s = s.replace("計畫", "計劃").replace("臺", "台")
    s = s.replace("-", "").replace(".", "").replace(",", "").replace("，", "")
    s = re.sub(r"\d+", lambda m: str(int(m.group())), s)
    return s


def span_in_answer(span: str, answer: str) -> bool:
    if span in answer:
        return True
    return _normalize_span_text(span) in _normalize_span_text(answer)


def login(client: httpx.Client) -> None:
    last = None
    for user in ("admin@enclave.local", "admin@example.com"):
        r = client.post(
            "/api/v1/auth/login/access-token",
            data={"username": user, "password": os.environ["EVAL_ADMIN_PASSWORD"]},
        )
        last = r
        if r.status_code == 200:
            client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
            return
    raise RuntimeError(f"login failed: {last.status_code if last else 'n/a'} {getattr(last, 'text', '')[:200]}")


def stream_answer(client: httpx.Client, question: str, timeout: int = 600) -> tuple[str, dict | None, list | None]:
    """回傳 (answer_text, retrieval_info, sources_info)。

    P0-3：額外 capture SSE retrieval/sources 事件，避免全域變數的執行緒安全問題。
    """
    collected: list[str] = []
    retrieval_info: dict | None = None
    sources_info: list | None = None
    try:
        with client.stream(
            "POST",
            "/api/v1/chat/chat/stream",
            json={"question": question},
            headers={"Accept": "text/event-stream"},
            timeout=httpx.Timeout(30.0, read=float(timeout)),
        ) as resp:
            if resp.status_code != 200:
                return (f"[ERROR {resp.status_code}] {resp.read().decode('utf-8', 'ignore')[:200]}", None, None)
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
                    collected.append(d["content"])
                elif d.get("type") == "retrieval":
                    retrieval_info = d.get("retrieval") or {}
                elif d.get("type") == "sources":
                    sources_info = d.get("sources") or []
                elif "content" in d and "type" not in d:
                    collected.append(d["content"])
    except Exception as exc:  # keep suite alive on any stream failure
        partial = "".join(collected)
        return (f"[ERROR {type(exc).__name__}] {exc}; partial={partial[:200]}", retrieval_info, sources_info)
    return ("".join(collected), retrieval_info, sources_info)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8001")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--with-expanded", action="store_true",
                    help="合併 z1_expanded_from_annotations.yaml")
    ap.add_argument("--questions", default="",
                    help="指定替代題庫 yaml（如 z2_blind_questions.yaml）")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 題（0=全部）")
    ap.add_argument("--offset", type=int, default=0, help="跳過前 N 題（續跑）")
    ap.add_argument("--resume-from", default="", help="從指定 question id 開始（含該題）")
    args = ap.parse_args()

    qpath = ROOT / "testdata" / "golden" / args.questions if args.questions else QUESTIONS
    questions = yaml.safe_load(qpath.read_text(encoding="utf-8"))["questions"]
    if args.with_expanded and EXPANDED.is_file():
        questions = questions + yaml.safe_load(EXPANDED.read_text(encoding="utf-8"))["questions"]
    if args.resume_from:
        ids = [q["id"] for q in questions]
        if args.resume_from not in ids:
            raise SystemExit(f"resume-from id not found: {args.resume_from}")
        questions = questions[ids.index(args.resume_from):]
    if args.offset and args.offset > 0:
        questions = questions[args.offset:]
    if args.limit and args.limit > 0:
        questions = questions[: args.limit]
    manifest = {e["id"]: e["name"] for e in json.loads(MANIFEST.read_text(encoding="utf-8"))["entries"]}

    client = httpx.Client(base_url=args.base, timeout=httpx.Timeout(30.0, read=300.0))
    login(client)
    online = client.get("/api/v1/documents/", params={"limit": 200}).json()
    if isinstance(online, dict):
        online = online.get("items") or online.get("data") or []
    online_names = {d.get("filename") for d in online}

    results = []
    t0 = time.time()
    infra_streak = 0
    for q in questions:
        exp = q["expected"]
        exp_docs = exp.get("document_ids") or []
        missing = [manifest.get(d, d) for d in exp_docs if manifest.get(d) not in online_names]
        try:
            answer, retrieval_info, sources_info = stream_answer(client, q["query"], timeout=300)
        except Exception as exc:  # noqa: BLE001 — keep suite running
            answer = f"[ERROR {type(exc).__name__}] {exc}"
            retrieval_info = None
            sources_info = None
        spans = exp.get("span_contains") or []
        span_hits = [s for s in spans if span_in_answer(s, answer)]

        forbidden = exp.get("must_not_contain") or []
        forbidden_hits = [s for s in forbidden if s in answer]

        if answer.startswith("[ERROR"):
            verdict = "fail"
            note = answer[:240]
            infra_streak += 1
        elif exp.get("must_refuse"):
            infra_streak = 0
            refused = any(m in answer for m in REFUSAL_MARKERS)
            verdict = "pass" if refused and not forbidden_hits else ("fail" if forbidden_hits else "review")
            note = "refusal marker present" if refused else "no refusal marker — possible fabrication"
            if forbidden_hits:
                note += f"; forbidden={forbidden_hits}"
        elif missing:
            infra_streak = 0
            verdict = "blocked"
            note = f"expected docs not online: {missing}"
        elif spans:
            infra_streak = 0
            ok = len(span_hits) == len(spans) and not forbidden_hits
            verdict = "pass" if ok else ("fail" if (not span_hits or forbidden_hits) else "review")
            note = f"spans {len(span_hits)}/{len(spans)}"
            if forbidden_hits:
                note += f"; forbidden={forbidden_hits}"
        else:
            infra_streak = 0
            verdict = "review"
            note = "no transcribed ground truth — needs human/agent judgement"

        # P0-3：分層診斷 — 區分「文件沒找到／段落漏掉／生成漏寫／安全門檻」
        retrieval_detail = retrieval_info or {}
        sources_detail = sources_info or []
        # 提取 retrieval rank 與 selected chunks
        retrieval_results = retrieval_detail.get("results") or retrieval_detail.get("chunks") or []
        retrieval_rank = [
            {
                "document_id": r.get("document_id", ""),
                "filename": r.get("filename", ""),
                "chunk_index": r.get("chunk_index"),
                "score": r.get("score", 0),
            }
            for r in retrieval_results[:10]  # 只記前 10 個
        ]
        # 判定 refusal reason
        refusal_reason = ""
        if verdict == "pass" and exp.get("must_refuse"):
            refusal_reason = "intended_refusal"
        elif verdict == "fail" and exp.get("must_refuse") and not any(m in answer for m in REFUSAL_MARKERS):
            refusal_reason = "should_refuse_but_didnt"
        elif verdict == "blocked":
            refusal_reason = "expected_docs_offline"
        elif retrieval_detail.get("refusal"):
            refusal_reason = retrieval_detail["refusal"].get("reason", "retrieval_refusal")
        # 分層診斷
        if verdict == "fail" and not exp.get("must_refuse"):
            if not retrieval_rank:
                diagnosis = "retrieval_miss"  # 文件沒找到
            elif len(span_hits) == len(spans) and spans:
                # 證據完整（所有 span 都在檢索結果中）但答案沒命中 → 生成漏寫
                diagnosis = "generation_miss"
            else:
                diagnosis = "chunk_miss"  # 文件找對但段落漏掉
        elif verdict == "pass" and exp.get("must_refuse"):
            diagnosis = "correct_refusal"
        elif verdict == "pass":
            diagnosis = "correct_answer"
        elif verdict == "blocked":
            diagnosis = "blocked_offline"
        elif verdict == "review":
            diagnosis = "needs_review"
        else:
            diagnosis = "unknown"

        results.append({
            "id": q["id"], "category": q.get("category"), "query": q["query"],
            "expected_docs": [manifest.get(d, d) for d in exp_docs],
            "missing_docs": missing,
            "spans_expected": spans, "spans_hit": span_hits,
            "answer": answer, "verdict": verdict, "note": note,
            # P0-3：retrieval 細節
            "retrieval_rank": retrieval_rank,
            "retrieval_total": len(retrieval_results),
            "retrieval_status": retrieval_detail.get("status", ""),
            "retrieval_refusal": retrieval_detail.get("refusal"),
            "sources": sources_detail[:5],
            "providers_called": retrieval_detail.get("providers_called", []),
            "refusal_reason": refusal_reason,
            "diagnosis": diagnosis,
        })
        print(f"{q['id']} [{q.get('category')}] verdict={verdict} {note}", flush=True)
        # incremental checkpoint so timeouts don't lose progress
        summary = {
            "total": len(results),
            "pass": sum(1 for r in results if r["verdict"] == "pass"),
            "fail": sum(1 for r in results if r["verdict"] == "fail"),
            "review": sum(1 for r in results if r["verdict"] == "review"),
            "blocked": sum(1 for r in results if r["verdict"] == "blocked"),
        }
        pathlib.Path(args.out).write_text(
            json.dumps({
                "gate": "answer-correctness-acceptance",
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "base_url": args.base,
                "method": "live chat stream; answer text judged vs human-annotated ground truth",
                "elapsed_s": round(time.time() - t0, 1),
                "summary": summary,
                "results": results,
                "partial": True,
            }, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        if answer.startswith("[ERROR") and infra_streak >= 2 and any(
            x in answer for x in ("ConnectError", "ReadError", "ReadTimeout", "404", "10054", "10061")
        ):
            print("ABORT consecutive infra errors — resume later", flush=True)
            break

    summary = {
        "total": len(results),
        "pass": sum(1 for r in results if r["verdict"] == "pass"),
        "fail": sum(1 for r in results if r["verdict"] == "fail"),
        "review": sum(1 for r in results if r["verdict"] == "review"),
        "blocked": sum(1 for r in results if r["verdict"] == "blocked"),
    }
    report = {
        "gate": "answer-correctness-acceptance",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "base_url": args.base,
        "method": "live chat stream; answer text judged vs human-annotated ground truth (Z1-1)",
        "elapsed_s": round(time.time() - t0, 1),
        "summary": summary,
        "results": results,
        "partial": False,
    }
    pathlib.Path(args.out).write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\nsummary:", json.dumps(summary, ensure_ascii=False))
    print("written:", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
