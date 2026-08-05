"""FD-QUERYPLAN — QueryPlan 結構化意圖閘門（FOUNDATION F4）。

固定查詢字串（禁止題號白名單），斷言 chat retrieval 事件含：
- query_plan.intent / arms / plan_version
- 複合盤點：intent=multi_hop 且 sub_queries≥2，arms 含 catalog
- 事實題：intent=fact，arms 不含 catalog（或僅 chunk）
- 跨語對照：intent=translate

Usage:
  python scripts/eval_foundation_queryplan_gate.py [--base http://localhost:8001]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

import httpx

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "foundation_queryplan_last_run.json"

CASES = [
    {
        "id": "plan_inventory",
        "query": "目前庫內哪些文件屬於財務憑證？列出檔名",
        "expect_intent": "inventory",
        "expect_arms_contain": ["catalog"],
        "min_sub_queries": 0,
    },
    {
        "id": "plan_composite_multi_hop",
        "query": "入出境相關文件與人資相關文件各有哪些？",
        "expect_intent": "multi_hop",
        "expect_arms_contain": ["catalog"],
        "min_sub_queries": 2,
    },
    {
        "id": "plan_fact",
        "query": "營業稅繳款書的統一編號是多少？",
        "expect_intent": "fact",
        "expect_arms_contain": ["chunk"],
        "forbid_arms": ["catalog"],
        "min_sub_queries": 0,
    },
    {
        "id": "plan_translate",
        "query": "ETI Base Code 條款編號與標題對照",
        "expect_intent": "translate",
        "expect_arms_contain": ["chunk"],
        "min_sub_queries": 0,
    },
]


def login(client: httpx.Client) -> None:
    r = client.post(
        "/api/v1/auth/login/access-token",
        data={"username": "admin@example.com", "password": "admin123"},
    )
    r.raise_for_status()
    client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"


def stream_retrieval(client: httpx.Client, question: str, timeout: int = 180) -> dict:
    retrieval: dict = {}
    with client.stream(
        "POST",
        "/api/v1/chat/chat/stream",
        json={"question": question},
        headers={"Accept": "text/event-stream"},
        timeout=timeout,
    ) as resp:
        if resp.status_code != 200:
            raise httpx.HTTPStatusError(
                f"chat stream HTTP {resp.status_code}",
                request=resp.request,
                response=resp,
            )
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
            if d.get("type") == "retrieval":
                retrieval = d.get("retrieval") or {}
            elif d.get("type") == "token":
                # 答案不影響判定；提早有 retrieval 即可
                if retrieval:
                    break
    return retrieval


def judge(case: dict, retrieval: dict) -> dict:
    violations: list[str] = []
    qp = retrieval.get("query_plan") or {}
    if not qp:
        violations.append("query_plan_missing: retrieval event lacks query_plan object")
        return {"verdict": "fail", "violations": violations, "observed": {"retrieval": retrieval}}

    intent = qp.get("intent")
    arms = list(qp.get("arms") or retrieval.get("arms") or [])
    subs = list(qp.get("sub_queries") or [])

    if intent != case["expect_intent"]:
        violations.append(
            f"intent_mismatch: expected {case['expect_intent']}, got {intent}"
        )
    for a in case.get("expect_arms_contain") or []:
        if a not in arms:
            violations.append(f"arm_missing: expected arm {a} in {arms}")
    for a in case.get("forbid_arms") or []:
        if a in arms:
            violations.append(f"arm_forbidden: {a} must not be in {arms} for this intent")
    if len(subs) < int(case.get("min_sub_queries") or 0):
        violations.append(
            f"sub_queries_insufficient: need ≥{case['min_sub_queries']}, got {subs}"
        )
    if not qp.get("plan_version"):
        violations.append("plan_version_missing")

    return {
        "verdict": "fail" if violations else "pass",
        "violations": violations,
        "observed": {
            "intent": intent,
            "arms": arms,
            "sub_queries": subs,
            "plan_version": qp.get("plan_version"),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8001")
    args = ap.parse_args()
    t0 = time.time()
    cases_out = []
    violations_all: list[str] = []
    status = "PASS"
    try:
        with httpx.Client(base_url=args.base, timeout=180.0) as client:
            login(client)
            for case in CASES:
                try:
                    retrieval = stream_retrieval(client, case["query"])
                    judged = judge(case, retrieval)
                except Exception as exc:
                    judged = {
                        "verdict": "blocked",
                        "violations": [f"blocked: {type(exc).__name__}: {exc}"],
                        "observed": {},
                    }
                row = {"id": case["id"], "query": case["query"], **judged}
                cases_out.append(row)
                if judged["verdict"] == "fail":
                    status = "FAIL"
                    violations_all.extend(judged["violations"])
                elif judged["verdict"] == "blocked" and status != "FAIL":
                    status = "BLOCKED"
                    violations_all.extend(judged["violations"])
    except Exception as exc:
        status = "BLOCKED"
        violations_all = [f"blocked: {type(exc).__name__}: {exc}"]

    summary = {
        "total": len(cases_out),
        "pass": sum(1 for c in cases_out if c["verdict"] == "pass"),
        "fail": sum(1 for c in cases_out if c["verdict"] == "fail"),
        "blocked": sum(1 for c in cases_out if c["verdict"] == "blocked"),
    }
    report = {
        "gate": "FD-QUERYPLAN",
        "schema_version": 1,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "base_url": args.base,
        "method": "live chat stream; assert query_plan intent/arms/sub_queries",
        "status": status,
        "contract_violations": violations_all,
        "elapsed_s": round(time.time() - t0, 1),
        "summary": summary,
        "cases": cases_out,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"status: {status} | summary: {json.dumps(summary)} | written: {OUT}")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
