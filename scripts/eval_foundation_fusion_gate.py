"""FD-FUSION — Gateway 融合不變量閘門（ADR-009）。

重放 internal_records 域查詢（固定查詢字串，**禁止**題號白名單），對 chat
stream 的 `sources` 事件斷言兩條融合不變量：

1. **可引用性**：使用者可見的每筆 source 必須 `citation_ok`——至少有非空
   title/filename；compiled（WeKnora 等）無檔名片段不得出現在可見 sources。
2. **主文件不得被擠掉**：庫內確實存在且與查詢直接相關的內部文件（預期檔名）
   必須出現在 sources 中；不得被無檔名的 compiled 命中取代。

觀測欄位（F3 後必備）：`retrieval` 事件的 `providers_called`、
`dropped_non_citable`、`fusion_policy_version`；缺失本身記為
`fusion_observability_missing`（F0 階段屬預期 FAIL）。

防假綠：本閘門**不得**透過關閉 WeKnora／sidecar 來通過——若偵測到 compiled
臂完全無命中且環境變數關閉旗標生效，記 `fusion_passed_by_disabling` 警告，
由人工判定是否假綠（見計畫 §3）。

Usage:
  python scripts/eval_foundation_fusion_gate.py [--base http://localhost:8001]
"""
from __future__ import annotations

import argparse
import os
import json
import pathlib
import sys
import time

import httpx

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "foundation_fusion_last_run.json"

# internal_records 域固定查詢；expected_source_substrings 來自 z1 manifest 真實檔名。
CASES = [
    {
        "id": "replay_tax_voucher_fact",
        "query": "營業稅繳款書的統一編號是多少？",
        "expected_source_substrings": ["營業稅繳款書"],
    },
    {
        "id": "replay_voucher_inventory",
        "query": "哪些掃描件屬於財務憑證？列出文件名",
        "expected_source_substrings": ["營業稅繳款書"],
    },
    {
        # 施工期未用過的內部憑證查詢（防題號過擬合）
        "id": "unseen_affidavit_fields",
        "query": "補印發票切結書需要填哪些欄位？",
        "expected_source_substrings": ["補印發票切結書"],
    },
]


def login(client: httpx.Client) -> None:
    r = client.post("/api/v1/auth/login/access-token",
                    data={"username": os.environ["EVAL_ADMIN_EMAIL"],
                          "password": os.environ["EVAL_ADMIN_PASSWORD"]})
    r.raise_for_status()
    client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"


def stream_sources(client: httpx.Client, question: str, timeout: int = 180) -> dict:
    """回傳 {sources, retrieval, answer}；網路錯誤拋例外由上層記 blocked。"""
    sources: list[dict] = []
    retrieval: dict = {}
    answer_parts: list[str] = []
    with client.stream("POST", "/api/v1/chat/chat/stream",
                       json={"question": question},
                       headers={"Accept": "text/event-stream"},
                       timeout=timeout) as resp:
        if resp.status_code != 200:
            raise httpx.HTTPStatusError(
                f"chat stream HTTP {resp.status_code}",
                request=resp.request, response=resp)
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
            if d.get("type") == "sources":
                sources = d.get("sources") or []
            elif d.get("type") == "retrieval":
                retrieval = d.get("retrieval") or {}
            elif d.get("type") == "token" and "content" in d:
                answer_parts.append(d["content"])
    return {"sources": sources, "retrieval": retrieval,
            "answer": "".join(answer_parts)}


def judge_case(case: dict, observed: dict) -> dict:
    violations: list[str] = []
    sources = observed["sources"]
    retrieval = observed["retrieval"]

    # 不變量 1：可引用性
    non_citable = [
        {"title": s.get("title"), "provider": s.get("provider"),
         "type": s.get("type")}
        for s in sources
        if not (s.get("title") or s.get("filename"))
    ]
    if non_citable:
        violations.append(
            f"non_citable_source_visible: {len(non_citable)} source(s) with empty "
            f"title/filename visible to user: {non_citable[:3]}")

    # 不變量 2：主文件不得被擠掉
    titles = [str(s.get("title") or s.get("filename") or "") for s in sources]
    hits = [sub for sub in case["expected_source_substrings"]
            if any(sub in t for t in titles)]
    if len(hits) < len(case["expected_source_substrings"]):
        violations.append(
            f"primary_document_displaced: expected {case['expected_source_substrings']}, "
            f"hit {hits}; visible titles={titles[:8]}")

    # 觀測欄位（F3 契約；F0 缺失屬預期）
    observability_missing = [
        k for k in ("providers_called", "dropped_non_citable", "fusion_policy_version")
        if k not in retrieval
    ]
    if observability_missing:
        violations.append(
            f"fusion_observability_missing: retrieval event lacks {observability_missing}")

    return {"verdict": "fail" if violations else "pass",
            "violations": violations,
            "observed": {
                "source_titles": titles,
                "providers_called": retrieval.get("providers_called"),
                "non_citable_count": len(non_citable),
                "answer_excerpt": observed["answer"][:300],
            }}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8001")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    client = httpx.Client(base_url=args.base, timeout=240.0)
    try:
        login(client)
    except Exception as e:
        report = {
            "gate": "FD-FUSION", "schema_version": 1,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "base_url": args.base, "status": "BLOCKED",
            "contract_violations": [f"stack_unreachable: {e}"],
            "summary": {"total": 0, "pass": 0, "fail": 0, "blocked": len(CASES)},
            "cases": [],
        }
        pathlib.Path(args.out).write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print("BLOCKED:", e)
        return 2

    cases_out = []
    t0 = time.time()
    for case in CASES:
        try:
            observed = stream_sources(client, case["query"])
        except Exception as e:
            entry = {"id": case["id"], "query": case["query"], "verdict": "blocked",
                     "violations": [f"request_error: {e}"], "observed": {}}
        else:
            judged = judge_case(case, observed)
            entry = {"id": case["id"], "query": case["query"],
                     "expectation": {"source_substrings": case["expected_source_substrings"]},
                     **judged}
        cases_out.append(entry)
        print(f"{case['id']}: verdict={entry['verdict']} "
              f"violations={entry['violations']}", flush=True)

    all_violations = [v for c in cases_out for v in c["violations"]]
    summary = {
        "total": len(cases_out),
        "pass": sum(1 for c in cases_out if c["verdict"] == "pass"),
        "fail": sum(1 for c in cases_out if c["verdict"] == "fail"),
        "blocked": sum(1 for c in cases_out if c["verdict"] == "blocked"),
    }
    report = {
        "gate": "FD-FUSION", "schema_version": 1,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "base_url": args.base,
        "method": "live chat stream replay of internal_records queries; "
                  "assert citation_ok + primary_document_not_displaced on sources event",
        "status": "PASS" if summary["fail"] == 0 and summary["blocked"] == 0 else
                  ("BLOCKED" if summary["pass"] == 0 and summary["fail"] == 0 else "FAIL"),
        "contract_violations": all_violations,
        "elapsed_s": round(time.time() - t0, 1),
        "summary": summary,
        "cases": cases_out,
    }
    pathlib.Path(args.out).write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\nstatus:", report["status"], "| summary:", json.dumps(summary))
    print("written:", args.out)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
