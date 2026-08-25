"""MKA 三劇本程式化 E2E 走查。

對應 docs/MKA_UX_TEST_SCRIPTS.md 的核心任務，全部透過 API 執行：
  A2 版本差異問答 / A3-A5 報價單建單→送審→核准→匯出
  B1 場景掃碼解析 / B2 場景限定問答 / B3 異常回報 / B4 交接班
  C1 訪談建卡 / C2 衝突阻擋→處置→送審 / C3 核准 / C4 新人查詢
  P  權限邊界（viewer）

前置：先跑 setup_test_env.py 與 ingest_docs.py，且 API 伺服器在 8005。
用法：cd Enclave && python test-materials/e2e/e2e_walkthrough.py
產出：test-materials/e2e/e2e_report.json
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

BASE = os.getenv("E2E_API_BASE", "http://127.0.0.1:8005/api/v1")
TM = ROOT / "test-materials"
REPORT = Path(__file__).parent / "e2e_report.json"

ADMIN = "admin"
SALES = "sales"
FIELD = "field"
MASTER = "master"
NEWCOMER = "newcomer"
VIEWER = "viewer"

RESULTS: list[dict] = []


def step(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append({"step": name, "pass": bool(ok), "detail": detail[:500]})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail[:200]}" if detail else ""))
    return ok


def login(client: httpx.Client, persona: str) -> dict:
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
    transcript = (TM / "C-knowhow" / "C1_語音腳本_師傅訪談逐字稿.md").read_text(encoding="utf-8")
    # 只取逐字稿本文（去掉評分對照區），模擬真實貼上
    if "## 逐字稿" in transcript:
        transcript = transcript.split("## 逐字稿", 1)[1].split("## 預期系統行為", 1)[0].strip()

    with httpx.Client(base_url=BASE, timeout=120.0) as client:
        admin = login(client, ADMIN)
        sales = login(client, SALES)
        field = login(client, FIELD)
        master = login(client, MASTER)
        newcomer = login(client, NEWCOMER)
        viewer = login(client, VIEWER)

        # ── Phase 0：環境驗證 ─────────────────────────────
        r = client.get("/experience/bootstrap", headers=sales)
        boot = r.json() if r.status_code == 200 else {}
        assignments = boot.get("job_role_assignments") or []
        step("0.1 業務 bootstrap 含職能指派", r.status_code == 200 and len(assignments) > 0,
             f"status={r.status_code} assignments={len(assignments)}")

        # ── 劇本 A ───────────────────────────────────────
        r = client.post("/chat/chat", headers=sales,
                        json={"question": "P-200 的 v2.0 和 v2.1 規格差在哪？"})
        ans = extract_answer(r.json()) if r.status_code == 200 else ""
        hits = sum(1 for kw in ("IP65", "CAN", "溫度") if kw in ans)
        step("A2 版本差異問答命中≥2項", r.status_code == 200 and hits >= 2,
             f"status={r.status_code} hits={hits} ans={ans[:150]}")

        # A3：建報價單（語音部分無法程式化，以結構化值代替）
        values = {
            "customer": "翔展科技", "part_number": "P-200", "quantity": 300,
            "unit_price": 1150, "valid_until": "2026-09-04", "payment_terms": "月結30天",
        }
        r = client.post("/forms/quote/instances", headers=sales,
                        json={"values": values, "module_key": "sales_quote"})
        inst = r.json() if r.status_code in (200, 201) else {}
        iid = inst.get("id") or inst.get("instance_id")
        step("A3 建立報價單草稿", bool(iid), f"status={r.status_code} {r.text[:150]}")

        if iid:
            cur = client.get(f"/forms/instances/{iid}", headers=sales).json()
            rv0 = cur.get("record_version", 1)
            r = client.post(f"/forms/instances/{iid}/validate", headers=sales,
                            json={"record_version": rv0})
            step("A3.1 表單驗證", r.status_code == 200, r.text[:150])
            cur = client.get(f"/forms/instances/{iid}", headers=sales).json()
            r = client.post(f"/forms/instances/{iid}/calculate", headers=sales,
                            json={"record_version": cur.get("record_version", rv0)})
            calc = r.json() if r.status_code == 200 else {}
            calc_txt = json.dumps(calc, ensure_ascii=False)
            step("A3.2 計算欄位（300×1150=345000）", "345000" in calc_txt, calc_txt[:200])

            cur = client.get(f"/forms/instances/{iid}", headers=sales).json()
            rv = cur.get("record_version", 1)
            r = client.post(f"/forms/instances/{iid}/submit", headers=sales,
                            json={"record_version": rv, "idempotency_key": f"e2e-quote-{uuid.uuid4()}"})
            step("A4 報價單送審", r.status_code in (200, 201), f"status={r.status_code} {r.text[:150]}")

            # A5：主管核准
            inbox = client.get("/approvals/inbox", headers=admin).json()
            ap = find_approval(inbox, "form", iid)
            step("A5.1 主管收件匣找到報價單", ap is not None,
                 f"inbox_size={len(inbox) if isinstance(inbox, list) else 'n/a'}")
            if ap:
                r = client.post(f"/approvals/{ap['id']}/approve", headers=admin, json={
                    "record_version": ap.get("record_version", 1),
                    "idempotency_key": f"e2e-appr-{uuid.uuid4()}",
                    "reason": "E2E 核准",
                })
                step("A5.2 主管核准", r.status_code == 200, r.text[:150])

            r = client.post(f"/forms/instances/{iid}/export", headers=sales,
                            json={"format": "docx"})
            ok = r.status_code == 200 and len(r.content) > 500
            step("A5.3 匯出 DOCX（公司版型）", ok,
                 f"status={r.status_code} bytes={len(r.content)} "
                 f"ctype={r.headers.get('content-type','')}")

        # ── 劇本 B ───────────────────────────────────────
        r = client.post("/scene/resolve", headers=field, json={"qr_token": "EQ100-DEMO-QR-001"})
        scene = r.json() if r.status_code == 200 else {}
        scene_ctx = scene.get("scene_context") or scene.get("context") or {}
        eq = scene_ctx.get("equipment_id") or scene.get("equipment_id")
        step("B1 掃碼解析 EQ-100 場景", eq == "EQ-100-01", f"status={r.status_code} eq={eq}")

        r = client.post("/scene/resolve", headers=field, json={"qr_token": "NOT-EXIST-QR"})
        step("B1.1 未註冊 QR fail-closed", r.status_code in (404, 400, 422),
             f"status={r.status_code}")

        r = client.post("/chat/chat", headers=field, json={
            "question": "E-07 怎麼處理？",
            "scene_context": {"equipment_id": "EQ-100-01"},
        })
        ans = extract_answer(r.json()) if r.status_code == 200 else ""
        hits = sum(1 for kw in ("停機", "張力計", "感知器") if kw in ans)
        step("B2 場景限定問答 E-07", r.status_code == 200 and hits >= 2,
             f"status={r.status_code} hits={hits} ans={ans[:150]}")

        b3_values = {
            "equipment_id": "EQ-100-01", "location": "二廠 A 產線",
            "occurred_at": "2026-08-06", "category": "設備故障",
            "severity": "嚴重（已停機）",
            "description": "機台異音後跳 E-03 停機，風扇有轉，之前修過軸承，待設備課檢查。",
            "immediate_action": "依 SOP 停機，未觸碰高溫部位",
            "reporter": "李阿明",
        }
        r = client.post("/forms/incident_report/instances", headers=field, json={
            "values": b3_values,
            "scene_context": {"equipment_id": "EQ-100-01"},
            "module_key": "incident_handover",
        })
        b3 = r.json() if r.status_code in (200, 201) else {}
        b3_id = b3.get("id") or b3.get("instance_id")
        step("B3 異常回報建單（含場景）", bool(b3_id), f"status={r.status_code} {r.text[:150]}")
        if b3_id:
            cur = client.get(f"/forms/instances/{b3_id}", headers=field).json()
            r = client.post(f"/forms/instances/{b3_id}/submit", headers=field, json={
                "record_version": cur.get("record_version", 1),
                "idempotency_key": f"e2e-inc-{uuid.uuid4()}"})
            step("B3.1 異常回報送審", r.status_code in (200, 201), r.text[:120])
            inbox = client.get("/approvals/inbox", headers=admin).json()
            ap = find_approval(inbox, "form", b3_id)
            if ap:
                r = client.post(f"/approvals/{ap['id']}/approve", headers=admin, json={
                    "record_version": ap.get("record_version", 1),
                    "idempotency_key": f"e2e-appr-{uuid.uuid4()}", "reason": "E2E"})
                step("B3.2 異常回報核准", r.status_code == 200, r.text[:120])

        b4_values = {
            "shift_date": "2026-08-06", "shift": "早班", "line": "二廠 A 產線",
            "outgoing": "李阿明", "incoming": "陳志豪",
            "production_summary": "EQ-100 跳 E-03 停機待修，其餘機台正常。",
            "pending_issues": "EQ-100 待設備課檢修軸承，復機後注意主軸溫度。",
            "equipment_notes": "E-03 停機中，禁止重啟。",
        }
        r = client.post("/forms/shift_handover/instances", headers=field,
                        json={"values": b4_values, "module_key": "incident_handover"})
        b4 = r.json() if r.status_code in (200, 201) else {}
        step("B4 交接班紀錄建單", bool(b4.get("id") or b4.get("instance_id")),
             f"status={r.status_code} {r.text[:150]}")

        # ── 劇本 C ───────────────────────────────────────
        r = client.post("/knowhow/interview/extract", headers=master, json={
            "transcript": transcript,
            "title": "張力異常（E-07）診斷與處理經驗",
            "equipment_id": "EQ-100-01",
            "consent": True,
        })
        card = r.json() if r.status_code in (200, 201) else {}
        card_id = (card.get("id") or card.get("card_id") or card.get("knowhow_id")
                   or (card.get("card") or {}).get("id"))
        step("C1 訪談建卡產生草稿", bool(card_id), f"status={r.status_code} {r.text[:200]}")

        if card_id:
            cur = client.get(f"/knowhow/{card_id}", headers=master).json()
            r = client.post(f"/knowhow/{card_id}/submit", headers=master, json={
                "version": cur.get("version", 1),
                "idempotency_key": f"e2e-kh-{uuid.uuid4()}"})
            blocked = r.status_code == 409 and "conflict" in r.text.lower()
            step("C2.1 未處置衝突阻擋送審（預期 409）", blocked,
                 f"status={r.status_code} {r.text[:150]}")

            cur = client.get(f"/knowhow/{card_id}", headers=master).json()
            report = cur.get("conflict_report") or []
            step("C2.2 衝突報告存在", len(report) > 0, f"conflicts={len(report)}")
            resolved = [{**c, "resolved": True, "resolution": "sop_wins：舊做法已廢止，卡片加註禁止"} for c in report]
            r = client.patch(f"/knowhow/{card_id}", headers=master,
                             json={"version": cur.get("version", 1),
                                   "values": {"conflict_report": resolved}})
            step("C2.3 標記衝突處置", r.status_code == 200, r.text[:120])

            cur = client.get(f"/knowhow/{card_id}", headers=master).json()
            r = client.post(f"/knowhow/{card_id}/submit", headers=master, json={
                "version": cur.get("version", 1),
                "idempotency_key": f"e2e-kh-{uuid.uuid4()}"})
            step("C2.4 處置後送審成功", r.status_code in (200, 201),
                 f"status={r.status_code} {r.text[:150]}")

            inbox = client.get("/approvals/inbox", headers=admin).json()
            ap = find_approval(inbox, "knowhow", card_id)
            if ap:
                r = client.post(f"/knowhow/{card_id}/approve", headers=admin, json={
                    "record_version": ap.get("record_version", 1),
                    "idempotency_key": f"e2e-khappr-{uuid.uuid4()}",
                    "reason": "E2E 核准"})
                step("C3 主管核准知識卡", r.status_code == 200, r.text[:150])
            else:
                step("C3 主管核准知識卡", False, "inbox 找不到 knowhow 審核請求")

            r = client.post("/chat/chat", headers=newcomer,
                            json={"question": "機台張力異常怎麼處理？"})
            ans = extract_answer(r.json()) if r.status_code == 200 else ""
            hits = sum(1 for kw in ("張力計", "停機", "15", "感知器") if kw in ans)
            step("C4 新人查詢命中知識", r.status_code == 200 and hits >= 1,
                 f"status={r.status_code} hits={hits} ans={ans[:150]}")

        # ── 權限邊界 ─────────────────────────────────────
        r = client.get("/audit/logs", headers=viewer)
        step("P1 viewer 禁查操作紀錄", r.status_code == 403, f"status={r.status_code}")
        r = client.get("/admin/users", headers=viewer)
        step("P2 viewer 禁查帳號管理", r.status_code == 403, f"status={r.status_code}")
        r = client.get("/job-modules", headers=viewer)
        step("P3 viewer 可查模組清單（唯讀）", r.status_code == 200, f"status={r.status_code}")

    passed = sum(1 for x in RESULTS if x["pass"])
    summary = {"passed": passed, "total": len(RESULTS), "results": RESULTS}
    REPORT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n=== E2E done: {passed}/{len(RESULTS)} passed ===")
    print(f"report: {REPORT}")


if __name__ == "__main__":
    main()
