"""FD-CATALOG — 多粒度檢索契約閘門（ADR-008）。

斷言「文件層（catalog）檢索臂」存在且可用，而非靠 chunk 相似度碰巧帶出檔名：

1. API 契約：`POST /api/v1/kb/search` 接受 `granularity=catalog` 並在回應中
   回顯實際使用的 granularity（防 silently ignored → 假綠）。
2. 檔名召回：固定盤點查詢（query 字串固定，**禁止**題號白名單）的預期檔名
   必須出現在 catalog 臂結果中。
3. Chat 路徑（--with-chat）：盤點題的 retrieval 事件必須顯示 catalog 臂被呼叫
   （`granularity`/`arms` 欄位），不得是 prompt-only 列檔名。

F0 階段允許 FAIL——F2 實作完成前，預期 contract_violations 含
`catalog_arm_missing`。通過條件見 FOUNDATION_RETRIEVAL_AND_DELIVERY_PLAN §0.3。

Usage:
  python scripts/eval_foundation_catalog_gate.py [--base http://localhost:8001] [--with-chat]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

import httpx

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "foundation_catalog_last_run.json"

# 固定查詢字串（非題號）；expected_filename_substrings 來自 z1 manifest 的真實檔名。
CASES = [
    {
        "id": "inventory_voucher",
        "query": "哪些掃描件屬於財務憑證？列出文件名",
        "expected_filename_substrings": ["營業稅繳款書", "補印發票切結書"],
    },
    {
        "id": "inventory_composite",
        "query": "入出境相關文件與人資相關文件各有哪些？",
        "expected_filename_substrings": ["e-Arrival", "nueip", "由你人資MOU"],
    },
]


def login(client: httpx.Client) -> None:
    r = client.post("/api/v1/auth/login/access-token",
                    data={"username": "admin@example.com", "password": "admin123"})
    r.raise_for_status()
    client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"


def probe_catalog_api(client: httpx.Client, case: dict) -> dict:
    """ granularity=catalog 契約探測 + 檔名召回。"""
    violations: list[str] = []
    try:
        r = client.post("/api/v1/kb/search",
                        json={"query": case["query"], "top_k": 20,
                              "granularity": "catalog"})
    except httpx.HTTPError as e:
        return {"verdict": "blocked", "violations": [f"request_error: {e}"],
                "observed": {}}

    observed: dict = {"status_code": r.status_code}
    if r.status_code != 200:
        violations.append(f"catalog_arm_missing: HTTP {r.status_code}")
        return {"verdict": "fail", "violations": violations, "observed": observed}

    body = r.json()
    used_granularity = body.get("granularity")
    observed["granularity_echo"] = used_granularity
    if used_granularity != "catalog":
        # 欄位被 pydantic 靜默吞掉 = catalog 臂不存在（chunk 假裝回答）
        violations.append("catalog_arm_missing: request granularity=catalog "
                          "not echoed in response (param silently ignored?)")

    filenames = [str(x.get("filename") or "") for x in body.get("results", [])]
    observed["filenames"] = filenames
    hits = [sub for sub in case["expected_filename_substrings"]
            if any(sub in fn for fn in filenames)]
    observed["expected_hits"] = hits
    if used_granularity == "catalog" and len(hits) < len(case["expected_filename_substrings"]):
        violations.append(
            f"catalog_recall: expected {case['expected_filename_substrings']}, "
            f"hit {hits}")

    return {"verdict": "fail" if violations else "pass",
            "violations": violations, "observed": observed}


def probe_chat_path(client: httpx.Client, case: dict, timeout: int = 120) -> dict:
    """盤點題在 chat 主路徑必須走 catalog 臂（retrieval 事件可觀測）。"""
    violations: list[str] = []
    retrieval_event: dict = {}
    with client.stream("POST", "/api/v1/chat/chat/stream",
                       json={"question": case["query"]},
                       headers={"Accept": "text/event-stream"},
                       timeout=timeout) as resp:
        if resp.status_code != 200:
            return {"verdict": "blocked",
                    "violations": [f"chat_http_{resp.status_code}"], "observed": {}}
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
                retrieval_event = d.get("retrieval") or {}

    observed = {"retrieval_event": retrieval_event}
    arms = retrieval_event.get("arms") or retrieval_event.get("granularity")
    if not arms or "catalog" not in str(arms):
        violations.append("chat_catalog_arm_missing: retrieval event shows no "
                          "catalog arm for inventory query (prompt-only listing?)")
    return {"verdict": "fail" if violations else "pass",
            "violations": violations, "observed": observed}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8001")
    ap.add_argument("--with-chat", action="store_true",
                    help="also probe the chat stream path (slow, uses LLM)")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    client = httpx.Client(base_url=args.base, timeout=180.0)
    try:
        login(client)
    except Exception as e:
        report = {
            "gate": "FD-CATALOG", "schema_version": 1,
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
        api_res = probe_catalog_api(client, case)
        entry = {"id": case["id"], "query": case["query"],
                 "expectation": {"filename_substrings": case["expected_filename_substrings"]},
                 "api": api_res}
        if args.with_chat:
            entry["chat"] = probe_chat_path(client, case)
        verdicts = [api_res["verdict"]] + ([entry["chat"]["verdict"]] if args.with_chat else [])
        entry["verdict"] = "fail" if "fail" in verdicts else (
            "blocked" if all(v == "blocked" for v in verdicts) else "pass")
        cases_out.append(entry)
        print(f"{case['id']}: verdict={entry['verdict']} "
              f"violations={api_res['violations']}", flush=True)

    all_violations = [v for c in cases_out for v in
                      (c["api"]["violations"] + (c.get("chat", {}).get("violations") or []))]
    summary = {
        "total": len(cases_out),
        "pass": sum(1 for c in cases_out if c["verdict"] == "pass"),
        "fail": sum(1 for c in cases_out if c["verdict"] == "fail"),
        "blocked": sum(1 for c in cases_out if c["verdict"] == "blocked"),
    }
    report = {
        "gate": "FD-CATALOG", "schema_version": 1,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "base_url": args.base,
        "method": "kb/search granularity=catalog contract probe + filename recall"
                  + (" + chat retrieval-arm probe" if args.with_chat else ""),
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
