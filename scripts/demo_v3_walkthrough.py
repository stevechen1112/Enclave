#!/usr/bin/env python3
"""依調整後 DEMO 劇本（v3 Task Workspace 主路徑）在生產執行走查。

對應 docs/MKA_DEMO_QUESTION_SET.md / MKA_UX_TEST_SCRIPTS.md §8
產出：artifacts/demo_v3_walkthrough_last_run.json
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = os.getenv("DEMO_API_BASE", "https://kachu.tw/api/v1")
REPORT = Path(__file__).resolve().parents[1] / "artifacts" / "demo_v3_walkthrough_last_run.json"

SALES = "sales"
FIELD = "field"
MASTER = "master"
NEWCOMER = "newcomer"
VIEWER = "viewer"
ADMIN = "admin"

RESULTS: list[dict] = []


def step(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append({"step": name, "pass": bool(ok), "detail": detail[:600]})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail[:200]}" if detail else ""))
    return ok


def login(client: httpx.Client, persona: str) -> dict:
    """Enter one of the six public Demo doors without handling credentials."""
    r = client.post("/auth/login/demo", json={"persona": persona})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def extract_answer(body) -> str:
    if isinstance(body, dict):
        for k in ("answer", "response", "message", "content", "text"):
            v = body.get(k)
            if isinstance(v, str) and v:
                return v
    return json.dumps(body, ensure_ascii=False)


def find_approval(inbox, object_type: str, object_id: str):
    items = inbox if isinstance(inbox, list) else inbox.get("items", inbox.get("results", []))
    for it in items:
        if it.get("object_type") == object_type and str(it.get("object_id")) == str(object_id):
            return it
    return None


def main() -> None:
    with httpx.Client(base_url=BASE, timeout=180.0) as client:
        admin = login(client, ADMIN)
        sales = login(client, SALES)
        field = login(client, FIELD)
        master = login(client, MASTER)
        newcomer = login(client, NEWCOMER)
        viewer = login(client, VIEWER)

        # ── 0. 工作台主路徑對齊 ──
        r = client.get("/experience/bootstrap", headers=sales)
        boot = r.json() if r.status_code == 200 else {}
        entries = boot.get("workspace_entries") or []
        quote_ep = next((e for e in entries if "報價" in (e.get("label") or "")), None)
        step(
            "0.1 業務『開報價單』指向 /job/tasks/quote",
            quote_ep is not None and (quote_ep.get("path") or "").startswith("/job/tasks/quote"),
            f"path={quote_ep.get('path') if quote_ep else None}",
        )
        r = client.get("/experience/bootstrap", headers=newcomer)
        newcomer_boot = r.json() if r.status_code == 200 else {}
        step(
            "0.2 新人門可進入專屬工作台",
            r.status_code == 200 and bool(newcomer_boot.get("workspace_entries")),
            f"entries={len(newcomer_boot.get('workspace_entries') or [])}",
        )

        # ── Demo A ──
        r = client.post("/chat/chat", headers=sales, json={
            "question": "P-200 的 v2.0 和 v2.1 規格差在哪？",
            "module_key": "spec_sop",
        })
        ans = extract_answer(r.json()) if r.status_code == 200 else ""
        hits = sum(1 for kw in ("IP65", "CAN", "溫度", "IP54") if kw in ans)
        step("A2 版本差異問答", r.status_code == 200 and hits >= 2,
             f"hits={hits} ans={ans[:160]}")

        r = client.post("/chat/chat", headers=sales, json={
            "question": "翔展科技要買 P-200 300 pcs，單價大概多少？有 MOQ 嗎？",
            "module_key": "sales_quote",
        })
        ans = extract_answer(r.json()) if r.status_code == 200 else ""
        price_hit = any(k in ans for k in ("1150", "1,150", "MOQ", "50"))
        step("A 詢價級距／MOQ", r.status_code == 200 and price_hit, ans[:160])

        # A3：Task Workspace 主路徑 — start → parse-text → patch 必填 → execute
        r = client.post(
            "/tasks/quote/runs",
            headers=sales,
            json={"idempotency_key": f"demo-v3-quote-{uuid.uuid4()}"},
        )
        run = r.json() if r.status_code in (200, 201) else {}
        run_id = run.get("id")
        step("A3.1 建立 quote TaskRun", bool(run_id), f"status={r.status_code}")

        if run_id:
            r = client.post(
                f"/tasks/runs/{run_id}/parse-text",
                headers=sales,
                json={"text": "幫翔展科技報價，料號 P-200，三百個，單價一千一百五十"},
            )
            body = r.json() if r.status_code == 200 else {}
            run = body.get("run") or body
            vals = (run.get("input_snapshot") or {}).get("values") or {}
            ok_extract = (
                vals.get("customer") == "翔展科技"
                and vals.get("part_number") == "P-200"
                and str(vals.get("quantity")) == "300"
                and str(vals.get("unit_price")).replace(",", "") in ("1150", "1,150")
            )
            step("A3.2 parse-text 抽出四欄", ok_extract, f"values={vals}")

            # 補齊 regex 未覆蓋的必填
            valid_until = (
                datetime.now(timezone.utc).date() + timedelta(days=30)
            ).isoformat()
            r = client.patch(
                f"/tasks/runs/{run_id}/inputs",
                headers=sales,
                json={
                    "values": {
                        "valid_until": valid_until,
                        "payment_terms": "月結30天",
                    },
                    "sources": {
                        "valid_until": {"source": "user"},
                        "payment_terms": {"source": "user"},
                    },
                    "edited_fields": ["valid_until", "payment_terms"],
                },
            )
            step("A3.3 手動補付款條件／有效期限", r.status_code == 200, r.text[:120])

            r = client.post(f"/tasks/runs/{run_id}/execute", headers=sales)
            executed = r.json() if r.status_code == 200 else {}
            refs = executed.get("output_refs") or (executed.get("run") or {}).get("output_refs") or {}
            # execute endpoint may return TaskRun
            if not refs and isinstance(executed, dict):
                refs = executed.get("output_refs") or {}
            if not refs:
                # refetch
                got = client.get(f"/tasks/runs/{run_id}", headers=sales).json()
                refs = got.get("output_refs") or {}
                executed = got
            form_id = refs.get("form_instance_id")
            approval_id = refs.get("approval_id")
            step(
                "A3.4 execute 建立表單並送審",
                bool(form_id) and bool(approval_id),
                f"form={form_id} approval={approval_id} status={executed.get('status')} refs={refs}",
            )

            if form_id:
                inbox = client.get("/approvals", headers=admin).json()
                ap = find_approval(inbox, "form", form_id)
                if ap is None and approval_id:
                    # try get by id
                    got = client.get(f"/approvals/{approval_id}", headers=admin)
                    ap = got.json() if got.status_code == 200 else None
                step("A5.1 主管收件匣可見報價單", ap is not None,
                     f"inbox_type={type(inbox).__name__}")
                if ap:
                    r = client.post(
                        f"/approvals/{ap['id']}/approve",
                        headers=admin,
                        json={
                            "record_version": ap.get("record_version", 1),
                            "idempotency_key": f"demo-v3-appr-{uuid.uuid4()}",
                            "reason": "DEMO v3 核准",
                        },
                    )
                    step("A5.2 主管核准", r.status_code == 200, r.text[:120])

                r = client.post(
                    f"/forms/instances/{form_id}/export",
                    headers=sales,
                    json={"format": "docx"},
                )
                step(
                    "A5.3 匯出 DOCX",
                    r.status_code == 200 and len(r.content) > 500,
                    f"status={r.status_code} bytes={len(r.content)}",
                )

        # 拒答
        r = client.post("/chat/chat", headers=sales, json={"question": "P-300 的規格是什麼？"})
        ans = extract_answer(r.json()) if r.status_code == 200 else ""
        refuse = any(k in ans for k in ("沒有", "找不到", "無法", "不足", "未"))
        step("A 收尾拒答 P-300", r.status_code == 200 and refuse, ans[:160])

        # ── Demo B ──
        r = client.post("/scene/resolve", headers=field, json={"qr_token": "EQ100-DEMO-QR-001"})
        scene = r.json() if r.status_code == 200 else {}
        ctx = scene.get("scene_context") or scene.get("context") or scene
        eq = ctx.get("equipment_id") or scene.get("equipment_id")
        step("B1 掃碼 EQ-100", eq in ("EQ-100-01", "EQ-100", "EQ100"), f"eq={eq} status={r.status_code}")

        r = client.post("/scene/resolve", headers=field, json={"qr_token": "NOT-EXIST-QR"})
        step("B1.1 未註冊 QR fail-closed", r.status_code in (400, 404, 422), f"status={r.status_code}")

        r = client.post("/chat/chat", headers=field, json={
            "question": "E-07 怎麼處理？",
            "scene_context": {"equipment_id": "EQ-100-01"},
        })
        ans = extract_answer(r.json()) if r.status_code == 200 else ""
        hits = sum(1 for kw in ("停機", "禁止", "張力", "安全") if kw in ans)
        step("B2 E-07 安全優先問答", r.status_code == 200 and hits >= 2,
             f"hits={hits} ans={ans[:160]}")

        r = client.post(
            "/tasks/incident/runs",
            headers=field,
            json={"idempotency_key": f"demo-v3-inc-{uuid.uuid4()}"},
        )
        run = r.json() if r.status_code in (200, 201) else {}
        run_id = run.get("id")
        if run_id:
            client.patch(
                f"/tasks/runs/{run_id}/inputs",
                headers=field,
                json={
                    "values": {
                        "equipment_id": "EQ-100-01",
                        "location": "二廠 A 產線",
                        "occurred_at": datetime.now(timezone.utc).date().isoformat(),
                        "category": "設備故障",
                        "severity": "嚴重（已停機）",
                        "description": "EQ-100 跳 E-07，張力飄移，已停機待設備課。",
                        "reporter": "現場測試",
                    },
                    "sources": {"description": {"source": "text"}},
                    "edited_fields": ["description"],
                },
            )
            r = client.post(f"/tasks/runs/{run_id}/execute", headers=field)
            got = client.get(f"/tasks/runs/{run_id}", headers=field).json()
            refs = got.get("output_refs") or {}
            step(
                "B3 incident TaskRun 送審",
                bool(refs.get("form_instance_id")) and bool(refs.get("approval_id")),
                f"refs={refs} http={r.status_code}",
            )

        r = client.post(
            "/tasks/handover/runs",
            headers=field,
            json={"idempotency_key": f"demo-v3-ho-{uuid.uuid4()}"},
        )
        run = r.json() if r.status_code in (200, 201) else {}
        run_id = run.get("id")
        if run_id:
            client.patch(
                f"/tasks/runs/{run_id}/inputs",
                headers=field,
                json={
                    "values": {
                        "shift_date": datetime.now(timezone.utc).date().isoformat(),
                        "shift": "晚班",
                        "line": "二廠 A 產線",
                        "outgoing": "現場測試",
                        "incoming": "下一班",
                        "production_summary": "EQ-100 E-07 已停機，待設備課。",
                        "pending_issues": "張力計校正",
                    },
                    "sources": {},
                    "edited_fields": [],
                },
            )
            r = client.post(f"/tasks/runs/{run_id}/execute", headers=field)
            got = client.get(f"/tasks/runs/{run_id}", headers=field).json()
            refs = got.get("output_refs") or {}
            step(
                "B4 handover TaskRun 送審",
                bool(refs.get("form_instance_id")),
                f"refs={refs} http={r.status_code}",
            )

        # ── Demo C（API 路徑：訪談抽取仍走 knowhow；任務工作區 interview execute 建草稿）──
        transcript = (
            "E-07 張力異常喔，我做二十幾年了，通常都是先看一下張力設定有沒有跑掉。"
            "老做法是用目測、用手感去判斷張力，覺得差不多就好。"
        )
        r = client.post("/knowhow/interview/extract", headers=master, json={
            "transcript": transcript,
            "consent": True,
            "title": "E-07 張力異常處理經驗",
            "equipment_id": "EQ-100-01",
        })
        extracted = r.json() if r.status_code == 200 else {}
        step("C1 訪談抽取", r.status_code == 200, str(extracted)[:160])

        # 權限
        r = client.get("/experience/bootstrap", headers=viewer)
        vboot = r.json() if r.status_code == 200 else {}
        vcaps = set(vboot.get("capabilities") or [])
        step(
            "P viewer 無 admin_home",
            "admin_home" not in vcaps,
            f"caps={sorted(vcaps)}",
        )

    passed = sum(1 for x in RESULTS if x["pass"])
    failed = sum(1 for x in RESULTS if not x["pass"])
    summary = {
        "base": BASE,
        "passed": passed,
        "failed": failed,
        "total": len(RESULTS),
        "results": RESULTS,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n=== {passed}/{len(RESULTS)} passed, {failed} failed ===")
    print(f"Report: {REPORT}")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
