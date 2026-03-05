#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Enclave 完整功能測試腳本
=========================
覆蓋範圍：
  P0  環境驗證 / 認證
  P1  文件上傳（含解析狀態輪詢）
  P2  知識庫搜尋（KB direct search）
  P3  RAG 問答品質（精選題目集）
  P4  多輪對話 + 對話管理
  P5  內容生成（5 種模板 + DOCX/PDF 匯出）
  P6  報告管理 CRUD
  P7  KB 維護（健康、分類、完整性掃描、備份、知識缺口）
  P8  部門管理（樹狀）
  P9  公司管理（成員邀請、配額、用量）
  P10 功能旗標管理
  P11 對話分析 + 稽核日誌 + CSV 匯出
  P12 Agent 資料夾監控（WatchFolder + 審核佇列）
  P13 效能抽樣（回應時間）

使用方式：
  python scripts/run_enclave_tests.py                    # 全部跑
  python scripts/run_enclave_tests.py --phase 12         # 只跑 P12 Agent
  python scripts/run_enclave_tests.py --phase 3          # 只跑 P3 問答品質
  python scripts/run_enclave_tests.py --skip-upload      # 跳過上傳（文件已存在）
"""

import argparse
import json
import os
import sys
import time
import datetime
import traceback
import requests
from pathlib import Path
from typing import Optional

# ─────────────────────────── 全域設定 ──────────────────────────────────────────
BASE_URL = "http://localhost:8001"
ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "admin123"

# 測試用帳號（會在 P0 自動建立）
HR_EMAIL = "hr_test@enclave.local"
HR_PASSWORD = "Test1234!"
HR_NAME = "測試HR人員"

# 本機路徑
AIHR_DOCS = Path(r"C:\Users\User\Desktop\aihr\test-data\company-documents")
ENCLAVE_ROOT = Path(r"C:\Users\User\Desktop\Enclave")
AGENT_WATCH_HOST = str(ENCLAVE_ROOT / "test-agent-watch")
AGENT_WATCH_CONTAINER = "/code/test-agent-watch"   # Docker volume 對應路徑

# ─────────────────────────── 列印工具 ──────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

passed = failed = skipped = 0
results_log: list = []


def ok(label: str, detail: str = ""):
    global passed
    passed += 1
    tag = f"{GREEN}✓ PASS{RESET}"
    print(f"  {tag}  {label}" + (f"  [{detail}]" if detail else ""))
    results_log.append({"status": "PASS", "label": label, "detail": detail})


def fail(label: str, detail: str = ""):
    global failed
    failed += 1
    tag = f"{RED}✗ FAIL{RESET}"
    print(f"  {tag}  {label}" + (f"  [{detail}]" if detail else ""))
    results_log.append({"status": "FAIL", "label": label, "detail": detail})


def skip(label: str, reason: str = ""):
    global skipped
    skipped += 1
    tag = f"{YELLOW}⊘ SKIP{RESET}"
    print(f"  {tag}  {label}" + (f"  ({reason})" if reason else ""))
    results_log.append({"status": "SKIP", "label": label, "detail": reason})


def section(title: str):
    print(f"\n{BOLD}{CYAN}{'─'*60}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'─'*60}{RESET}")


# ─────────────────────────── HTTP 工具 ──────────────────────────────────────────
class API:
    def __init__(self):
        self.token: Optional[str] = None
        self.session = requests.Session()

    def _h(self, extra: Optional[dict] = None) -> dict:
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        if extra:
            h.update(extra)
        return h

    def login(self, email: str, password: str) -> bool:
        r = self.session.post(
            f"{BASE_URL}/api/v1/auth/login/access-token",
            data={"username": email, "password": password},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        if r.status_code == 200 and "access_token" in r.json():
            self.token = r.json()["access_token"]
            return True
        return False

    def get(self, path: str, params: Optional[dict] = None, timeout: int = 30):
        return self.session.get(
            f"{BASE_URL}{path}", params=params,
            headers=self._h(), timeout=timeout,
        )

    def post(self, path: str, json_body=None, data=None, files=None, timeout: int = 60):
        if files:
            h = {"Authorization": f"Bearer {self.token}"} if self.token else {}
            return self.session.post(
                f"{BASE_URL}{path}", data=data, files=files,
                headers=h, timeout=timeout,
            )
        return self.session.post(
            f"{BASE_URL}{path}", json=json_body,
            headers=self._h(), timeout=timeout,
        )

    def put(self, path: str, json_body=None, timeout: int = 30):
        return self.session.put(
            f"{BASE_URL}{path}", json=json_body,
            headers=self._h(), timeout=timeout,
        )

    def patch(self, path: str, json_body=None, timeout: int = 30):
        return self.session.patch(
            f"{BASE_URL}{path}", json=json_body,
            headers=self._h(), timeout=timeout,
        )

    def delete(self, path: str, timeout: int = 30):
        return self.session.delete(
            f"{BASE_URL}{path}", headers=self._h(), timeout=timeout,
        )

    def stream_sse(self, path: str, json_body: dict, timeout: int = 120) -> str:
        """讀取 SSE 串流，合併 content 欄位回傳完整文字"""
        h = self._h()
        h["Accept"] = "text/event-stream"
        collected = []
        try:
            with self.session.post(
                f"{BASE_URL}{path}", json=json_body,
                headers=h, stream=True, timeout=timeout,
            ) as resp:
                if resp.status_code != 200:
                    return f"[ERROR {resp.status_code}] {resp.text[:200]}"
                for raw in resp.iter_lines():
                    if not raw:
                        continue
                    line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
                    if not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        d = json.loads(data_str)
                        # chat/chat/stream: type=token; generate/stream: plain content
                        if d.get("type") == "token" and "content" in d:
                            collected.append(d["content"])
                        elif "content" in d and "type" not in d:
                            collected.append(d["content"])
                    except json.JSONDecodeError:
                        pass
        except Exception as e:
            return f"[ERROR] {e}"
        return "".join(collected)


api = API()


# ════════════════════════════════════════════════════════════════════════════════
# Phase 0 ─ 環境驗證 + 帳號設定
# ════════════════════════════════════════════════════════════════════════════════
def phase0():
    section("P0  環境驗證 / 認證")

    # 健康檢查
    try:
        r = requests.get(f"{BASE_URL}/health", timeout=5)
        if r.status_code == 200 and r.json().get("status") == "ok":
            ok("健康檢查", f"env={r.json().get('env', '?')}")
        else:
            fail("健康檢查", f"HTTP {r.status_code}")
    except Exception as e:
        fail("健康檢查", str(e))
        sys.exit(1)

    # Admin 登入
    if api.login(ADMIN_EMAIL, ADMIN_PASSWORD):
        ok("Admin 登入", ADMIN_EMAIL)
    else:
        fail("Admin 登入")
        sys.exit(1)

    # 建立測試 HR 人員（若不存在）
    r = api.post("/api/v1/company/users/invite", {
        "email": HR_EMAIL, "full_name": HR_NAME,
        "password": HR_PASSWORD, "role": "hr",
    })
    if r.status_code in (200, 201):
        ok("建立測試 HR 帳號", HR_EMAIL)
    elif r.status_code == 409:
        ok("測試 HR 帳號已存在", "跳過建立")
    else:
        fail("建立測試 HR 帳號", r.text[:100])

    # 取得目前使用者資訊
    r = api.get("/api/v1/users/me")
    if r.status_code == 200:
        u = r.json()
        ok("取得 me 資訊", f"role={u.get('role')} tenant={str(u.get('tenant_id',''))[:8]}...")
    else:
        fail("取得 me 資訊", f"HTTP {r.status_code}")


# ════════════════════════════════════════════════════════════════════════════════
# Phase 1 ─ 文件上傳
# ════════════════════════════════════════════════════════════════════════════════
def phase1(skip_upload: bool = False):
    section("P1  文件上傳")
    if skip_upload:
        skip("文件上傳", "--skip-upload 已設定")
        return []

    upload_targets = []
    for sub in ["hr-regulations", "sop", "payroll"]:
        d = AIHR_DOCS / sub
        if d.exists():
            for f in d.iterdir():
                if f.suffix.lower() in (".pdf", ".docx", ".txt", ".md"):
                    if f.stat().st_size < 20_000_000:
                        upload_targets.append(f)
                        if len(upload_targets) >= 8:
                            break
        if len(upload_targets) >= 8:
            break

    if not upload_targets:
        skip("文件上傳", "找不到測試文件")
        return []

    doc_ids = []
    for fp in upload_targets:
        with open(fp, "rb") as fh:
            r = api.post(
                "/api/v1/documents/upload",
                files={"file": (fp.name, fh, "application/octet-stream")},
                data={"auto_process": "true"},
            )
        if r.status_code in (200, 201):
            doc_id = r.json().get("id") or r.json().get("document_id")
            doc_ids.append(doc_id)
            ok(f"上傳 {fp.name[:40]}", f"id={str(doc_id)[:8]}...")
        else:
            fail(f"上傳 {fp.name[:40]}", f"HTTP {r.status_code} {r.text[:80]}")

    if not doc_ids:
        return []

    # 輪詢解析狀態（最多 120s）
    print(f"\n  ⏳ 等待解析完成（最多 120 秒）...")
    deadline = time.time() + 120
    while time.time() < deadline:
        time.sleep(8)
        r = api.get("/api/v1/documents/", params={"limit": 20})
        if r.status_code != 200:
            break
        raw = r.json()
        docs = raw if isinstance(raw, list) else raw.get("documents", raw.get("items", []))
        id_strs = [str(i) for i in doc_ids]
        done_count = sum(
            1 for d in docs
            if str(d.get("id")) in id_strs and d.get("status") in ("completed", "failed")
        )
        print(f"    {done_count}/{len(doc_ids)} 完成  ", end="\r")
        if done_count >= len(doc_ids):
            break

    print()
    r = api.get("/api/v1/documents/", params={"limit": 20})
    if r.status_code == 200:
        raw = r.json()
        docs = raw if isinstance(raw, list) else raw.get("documents", raw.get("items", []))
        id_strs = [str(i) for i in doc_ids]
        for d in docs:
            if str(d.get("id")) in id_strs:
                st = d.get("status", "?")
                name = d.get("filename", d.get("title", "?"))[:35]
                (ok if st == "completed" else fail)(
                    f"解析狀態 {name}",
                    f"status={st} chunks={d.get('chunk_count', '?')}",
                )
    return doc_ids


# ════════════════════════════════════════════════════════════════════════════════
# Phase 2 ─ 知識庫搜尋
# ════════════════════════════════════════════════════════════════════════════════
def phase2():
    section("P2  知識庫搜尋")

    r = api.get("/api/v1/kb/stats")
    if r.status_code == 200:
        s = r.json()
        ok("KB 統計", f"chunks={s.get('total_chunks',0)} vectors={s.get('vector_count',0)} dim={s.get('dimension','?')}")
    else:
        fail("KB 統計", f"HTTP {r.status_code}")

    queries = [
        ("勞工退休金提撥率", 1),
        ("年度考核流程",     1),
        ("請假規定 特休",    1),
        ("薪資計算方式",     1),
    ]
    for q, min_hits in queries:
        r = api.post("/api/v1/kb/search", {
            "query": q, "top_k": 5, "search_mode": "hybrid",
        })
        if r.status_code == 200:
            data = r.json()
            results = data if isinstance(data, list) else data.get("results", data.get("chunks", []))
            hits = len(results)
            (ok if hits >= min_hits else fail)(
                f"KB 搜尋「{q}」",
                f"{hits} 筆 (期望 ≥{min_hits})",
            )
        else:
            fail(f"KB 搜尋「{q}」", f"HTTP {r.status_code}")


# ════════════════════════════════════════════════════════════════════════════════
# Phase 3 ─ RAG 問答品質
# ════════════════════════════════════════════════════════════════════════════════
QA_SAMPLES = [
    # (問題, 期待關鍵字列表, 類別)
    ("員工試用期最長可以多久",            ["試用", "期", "月"],        "A 基本HR"),
    ("公司每年特休假天數怎麼計算",         ["特休", "天", "年"],        "A 假勤"),
    ("勞工退休金雇主應提撥多少比例",       ["6%", "提撥", "退休"],      "D 計算"),
    ("員工違反工作規則可以怎麼處理",       ["懲處", "警告", "規則"],    "A HR規範"),
    ("請問公司薪資發放日是幾號",           ["薪資", "發放"],            "A 薪酬"),
]


def phase3():
    section("P3  RAG 問答品質")
    print("  ℹ️  每題使用 SSE 串流，預計耗時 30~60 秒/題")

    conv_id = None
    scores = []

    for q, keywords, cat in QA_SAMPLES:
        t0 = time.time()
        body = {"question": q}
        if conv_id:
            body["conversation_id"] = conv_id

        answer = api.stream_sse("/api/v1/chat/chat/stream", body, timeout=90)
        elapsed = time.time() - t0

        if answer.startswith("[ERROR"):
            fail(f"[{cat}] {q[:30]}", answer[:80])
            scores.append(0)
            continue

        # 嘗試取最新 conv_id
        try:
            cr = api.get("/api/v1/chat/conversations", params={"limit": 1})
            if cr.status_code == 200:
                raw = cr.json()
                items = raw if isinstance(raw, list) else raw.get("items", raw.get("conversations", []))
                if items:
                    conv_id = items[0].get("id")
        except Exception:
            pass

        hit = sum(1 for kw in keywords if kw in answer)
        score = round(hit / len(keywords), 2)
        scores.append(score)
        (ok if score >= 0.5 else fail)(
            f"[{cat}] {q[:30]}",
            f"關鍵字 {hit}/{len(keywords)}  {elapsed:.1f}s  {len(answer)}chars",
        )

    avg = sum(scores) / len(scores) if scores else 0
    print(f"\n  📊 平均關鍵字命中率: {avg*100:.0f}%  (共 {len(scores)} 題)")
    return conv_id


# ════════════════════════════════════════════════════════════════════════════════
# Phase 4 ─ 多輪對話 + 對話管理
# ════════════════════════════════════════════════════════════════════════════════
def phase4(conv_id=None):
    section("P4  多輪對話 + 對話管理")

    r = api.get("/api/v1/chat/conversations", params={"limit": 5})
    if r.status_code == 200:
        raw = r.json()
        items = raw if isinstance(raw, list) else raw.get("items", raw.get("conversations", []))
        ok("取得對話清單", f"{len(items)} 筆")
        if not conv_id and items:
            conv_id = items[0].get("id")
    else:
        fail("取得對話清單", f"HTTP {r.status_code}")

    if not conv_id:
        skip("後續對話測試", "無對話 ID")
        return

    # 搜尋對話
    r = api.get("/api/v1/chat/conversations/search", params={"q": "特休", "limit": 5})
    if r.status_code == 200:
        raw = r.json()
        items = raw if isinstance(raw, list) else raw.get("items", raw.get("conversations", []))
        ok("搜尋對話「特休」", f"{len(items)} 筆")
    else:
        fail("搜尋對話", f"HTTP {r.status_code}")

    # 取單一對話
    r = api.get(f"/api/v1/chat/conversations/{conv_id}")
    if r.status_code == 200:
        ok("取得對話詳情")
    else:
        fail("取得對話詳情", f"HTTP {r.status_code}")

    # 取訊息（同時取得 message_id 供 feedback 使用）
    r = api.get(f"/api/v1/chat/conversations/{conv_id}/messages", params={"limit": 10})
    msg_id = None
    if r.status_code == 200:
        raw = r.json()
        msgs = raw if isinstance(raw, list) else raw.get("messages", raw.get("items", []))
        ok("取得對話訊息", f"{len(msgs)} 則")
        # 取 assistant 訊息的 id
        for m in msgs:
            if m.get("role") == "assistant":
                msg_id = m.get("id")
                break
        if not msg_id and msgs:
            msg_id = msgs[-1].get("id")
    else:
        fail("取得對話訊息", f"HTTP {r.status_code}")

    # 匯出對話
    r = api.get(f"/api/v1/chat/conversations/{conv_id}/export", params={"format": "json"})
    if r.status_code == 200:
        ok("匯出對話 JSON")
    else:
        fail("匯出對話 JSON", f"HTTP {r.status_code}")

    # Feedback (FeedbackCreate: message_id, rating 1/2)
    if msg_id:
        r = api.post("/api/v1/chat/feedback", {
            "message_id": str(msg_id),
            "rating": 2,  # 1=👎, 2=👍
            "comment": "自動測試回饋",
        })
        if r.status_code in (200, 201):
            ok("送出對話回饋（rating=2 👍）")
        else:
            fail("送出對話回饋", f"HTTP {r.status_code} {r.text[:100]}")
    else:
        skip("送出對話回饋", "無 message_id")

    # Feedback 統計
    r = api.get("/api/v1/chat/feedback/stats")
    if r.status_code == 200:
        ok("取得回饋統計")
    else:
        fail("取得回饋統計", f"HTTP {r.status_code}")

    # RAG Dashboard
    r = api.get("/api/v1/chat/dashboard/rag")
    if r.status_code == 200:
        ok("RAG Dashboard")
    else:
        fail("RAG Dashboard", f"HTTP {r.status_code}")


# ════════════════════════════════════════════════════════════════════════════════
# Phase 5 ─ 內容生成
# ════════════════════════════════════════════════════════════════════════════════
# Enclave generate templates: draft_response, case_summary, meeting_minutes, analysis_report, faq_draft
TEMPLATES_TEST = [
    ("draft_response",   "致顧客的遠距辦公政策公告函"),
    ("case_summary",     "員工違規懲處案件摘要：張三 2026Q1"),
    ("meeting_minutes",  "2026年3月部門主管會議記錄"),
    ("analysis_report",  "2025年度員工離職率趨勢分析"),
    ("faq_draft",        "新進員工常見人事問題 FAQ"),
]


def phase5():
    section("P5  內容生成（模板 + DOCX/PDF 匯出）")

    # 取得模板清單
    r = api.get("/api/v1/generate/templates")
    if r.status_code == 200:
        tmpls = r.json()
        tlist = tmpls.get("templates", tmpls) if isinstance(tmpls, dict) else tmpls
        ok("取得模板清單", f"{len(tlist)} 種: {', '.join(t.get('id','?') for t in tlist[:5])}")
    else:
        fail("取得模板清單", f"HTTP {r.status_code}")

    generated_content = ""
    generated_title = ""

    for tpl, prompt in TEMPLATES_TEST[:3]:
        t0 = time.time()
        content = api.stream_sse("/api/v1/generate/stream", {
            "template": tpl,
            "user_prompt": prompt,
            "context_query": prompt,
        }, timeout=120)
        elapsed = time.time() - t0
        if content.startswith("[ERROR"):
            fail(f"生成 [{tpl}]", content[:80])
        else:
            ok(f"生成 [{tpl}]", f"{len(content)} chars  {elapsed:.1f}s")
            if not generated_content:
                generated_content = content
                generated_title = prompt[:30]

    if generated_content:
        r = api.post("/api/v1/generate/export/docx", {
            "content": generated_content[:3000],
            "title": generated_title,
            "sources": [],
        })
        if r.status_code == 200 and len(r.content) > 100:
            ok("匯出 DOCX", f"{len(r.content)} bytes")
        else:
            fail("匯出 DOCX", f"HTTP {r.status_code}")

        r = api.post("/api/v1/generate/export/pdf", {
            "content": generated_content[:3000],
            "title": generated_title,
            "sources": [],
        })
        if r.status_code == 200 and len(r.content) > 100:
            ok("匯出 PDF", f"{len(r.content)} bytes")
        else:
            fail("匯出 PDF", f"HTTP {r.status_code}")
    else:
        skip("匯出 DOCX/PDF", "無可用生成內容")


# ════════════════════════════════════════════════════════════════════════════════
# Phase 6 ─ 報告管理 CRUD
# ════════════════════════════════════════════════════════════════════════════════
def phase6():
    section("P6  報告管理 CRUD")

    r = api.get("/api/v1/generate/reports")
    if r.status_code == 200:
        raw = r.json()
        items = raw if isinstance(raw, list) else raw.get("reports", raw.get("items", []))
        ok("取得報告清單", f"{len(items)} 筆")
    else:
        fail("取得報告清單", f"HTTP {r.status_code}")

    r = api.post("/api/v1/generate/reports", {
        "title": "自動測試報告_" + datetime.datetime.now().strftime("%H%M%S"),
        "template": "meeting_minutes",
        "prompt": "自動測試報告的提示詞",
        "content": "這是自動測試產生的報告內容，用於驗證報告儲存 API。",
        "document_ids": [],
    })
    created_id = None
    if r.status_code in (200, 201):
        created_id = r.json().get("id")
        ok("建立報告", f"id={str(created_id)[:8]}...")
    else:
        fail("建立報告", f"HTTP {r.status_code} {r.text[:100]}")

    if created_id:
        r = api.patch(f"/api/v1/generate/reports/{created_id}", {"is_pinned": True})
        if r.status_code == 200:
            ok("釘選報告")
        else:
            fail("釘選報告", f"HTTP {r.status_code}")

        r = api.get("/api/v1/generate/reports", params={"search": "自動測試"})
        if r.status_code == 200:
            raw = r.json()
            hits = raw if isinstance(raw, list) else raw.get("reports", raw.get("items", []))
            ok("搜尋報告「自動測試」", f"{len(hits)} 筆")
        else:
            fail("搜尋報告", f"HTTP {r.status_code}")

        r = api.delete(f"/api/v1/generate/reports/{created_id}")
        if r.status_code in (200, 204):
            ok("刪除報告")
        else:
            fail("刪除報告", f"HTTP {r.status_code}")


# ════════════════════════════════════════════════════════════════════════════════
# Phase 7 ─ KB 維護
# ════════════════════════════════════════════════════════════════════════════════
def phase7():
    section("P7  KB 維護（健康、分類、完整性、備份、知識缺口）")

    r = api.get("/api/v1/kb-maintenance/kb/health")
    if r.status_code == 200:
        h = r.json()
        ok("KB 健康狀態", f"docs={h.get('total_documents',0)} completed={h.get('completed_documents',0)} coverage={h.get('index_coverage_pct','?')}% conf7d={h.get('avg_confidence_7d','N/A')}")
    else:
        fail("KB 健康狀態", f"HTTP {r.status_code}")

    r = api.get("/api/v1/kb-maintenance/kb/categories")
    if r.status_code == 200:
        cats = r.json()
        total = len(cats) if isinstance(cats, list) else len(cats.get("categories", [cats]))
        ok("KB 分類清單", f"{total} 筆")
    else:
        fail("KB 分類清單", f"HTTP {r.status_code}")

    cat_name = "自動測試分類_" + datetime.datetime.now().strftime("%H%M%S")
    r = api.post("/api/v1/kb-maintenance/kb/categories", {
        "name": cat_name,
        "description": "由自動測試腳本建立的測試分類",
    })
    cat_id = None
    if r.status_code in (200, 201):
        cat_id = r.json().get("id")
        ok("建立分類", f"id={str(cat_id)[:8]}...")
    else:
        fail("建立分類", f"HTTP {r.status_code} {r.text[:100]}")

    r = api.post("/api/v1/kb-maintenance/kb/integrity/scan", {})
    if r.status_code in (200, 201, 202):
        ok("觸發完整性掃描")
    else:
        fail("觸發完整性掃描", f"HTTP {r.status_code}")

    r = api.get("/api/v1/kb-maintenance/kb/integrity/reports")
    if r.status_code == 200:
        rpts = r.json()
        cnt = len(rpts) if isinstance(rpts, list) else len(rpts.get("reports", []))
        ok("完整性報告清單", f"{cnt} 筆")
    else:
        fail("完整性報告清單", f"HTTP {r.status_code}")

    r = api.post("/api/v1/kb-maintenance/kb/backups", {
        "note": "自動測試備份 " + datetime.datetime.now().isoformat(),
    })
    if r.status_code in (200, 201, 202):
        ok("建立 KB 備份")
    else:
        fail("建立 KB 備份", f"HTTP {r.status_code} {r.text[:100]}")

    r = api.get("/api/v1/kb-maintenance/kb/backups")
    if r.status_code == 200:
        bkps = r.json()
        cnt = len(bkps) if isinstance(bkps, list) else len(bkps.get("backups", []))
        ok("備份清單", f"{cnt} 筆")
    else:
        fail("備份清單", f"HTTP {r.status_code}")

    r = api.get("/api/v1/kb-maintenance/kb/gaps")
    if r.status_code == 200:
        gaps = r.json()
        cnt = len(gaps) if isinstance(gaps, list) else len(gaps.get("gaps", []))
        ok("知識缺口清單", f"{cnt} 筆")
    else:
        fail("知識缺口清單", f"HTTP {r.status_code}")

    # KB 版本為 per-document API：/kb-maintenance/documents/{id}/versions
    # 查有無已上傳文件可取版本
    dr = api.get("/api/v1/documents/", params={"limit": 1})
    if dr.status_code == 200:
        raw = dr.json()
        docs = raw if isinstance(raw, list) else raw.get("documents", raw.get("items", []))
        if docs:
            doc_id = docs[0].get("id")
            r = api.get(f"/api/v1/kb-maintenance/documents/{doc_id}/versions")
            if r.status_code == 200:
                vs = r.json()
                cnt = len(vs) if isinstance(vs, list) else len(vs.get("versions", []))
                ok("KB 版本清單（per-doc）", f"{cnt} 筆")
            else:
                fail("KB 版本清單", f"HTTP {r.status_code}")
        else:
            skip("KB 版本清單", "無已上傳文件")
    else:
        skip("KB 版本清單", "無法取得文件清單")


# ════════════════════════════════════════════════════════════════════════════════
# Phase 8 ─ 部門管理
# ════════════════════════════════════════════════════════════════════════════════
def phase8():
    section("P8  部門管理")

    r = api.post("/api/v1/departments/", {
        "name": "測試研發部", "code": "RD_TEST",
        "description": "自動測試用部門",
    })
    dept_id = None
    if r.status_code in (200, 201):
        dept_id = r.json().get("id")
        ok("建立部門「測試研發部」", f"id={str(dept_id)[:8]}...")
    elif r.status_code == 409:
        # 已存在，取得 id
        lr = api.get("/api/v1/departments/")
        if lr.status_code == 200:
            raw = lr.json()
            items = raw if isinstance(raw, list) else raw.get("departments", raw.get("items", []))
            for dept in items:
                if dept.get("code") == "RD_TEST":
                    dept_id = dept.get("id")
                    break
        ok("部門已存在", "取得現有 ID")
    else:
        fail("建立部門", f"HTTP {r.status_code} {r.text[:100]}")

    sub_id = None
    if dept_id:
        r = api.post("/api/v1/departments/", {
            "name": "後端團隊", "code": "BE_TEST",
            "parent_id": dept_id,
        })
        if r.status_code in (200, 201):
            sub_id = r.json().get("id")
            ok("建立子部門「後端團隊」")
        elif r.status_code == 409:
            ok("子部門已存在")
        else:
            fail("建立子部門", f"HTTP {r.status_code}")

    r = api.get("/api/v1/departments/")
    if r.status_code == 200:
        raw = r.json()
        items = raw if isinstance(raw, list) else raw.get("departments", raw.get("items", []))
        ok("部門清單", f"{len(items)} 筆")
    else:
        fail("部門清單", f"HTTP {r.status_code}")

    r = api.get("/api/v1/departments/tree")
    if r.status_code == 200:
        ok("部門樹狀結構")
    else:
        fail("部門樹狀結構", f"HTTP {r.status_code}")

    if dept_id:
        r = api.put(f"/api/v1/departments/{dept_id}", {
            "name": "測試研發部（已更新）",
            "description": "自動測試更新",
        })
        if r.status_code == 200:
            ok("更新部門")
        else:
            fail("更新部門", f"HTTP {r.status_code}")

    # 清除測試部門
    if sub_id:
        api.delete(f"/api/v1/departments/{sub_id}")
    if dept_id:
        r = api.delete(f"/api/v1/departments/{dept_id}")
        if r.status_code in (200, 204):
            ok("刪除測試部門（含子部門）")
        else:
            fail("刪除測試部門", f"HTTP {r.status_code}")


# ════════════════════════════════════════════════════════════════════════════════
# Phase 9 ─ 公司管理
# ════════════════════════════════════════════════════════════════════════════════
def phase9():
    section("P9  公司管理（Dashboard / 配額 / 成員 / 用量）")

    r = api.get("/api/v1/company/dashboard")
    if r.status_code == 200:
        ok("公司 Dashboard")
    else:
        fail("公司 Dashboard", f"HTTP {r.status_code}")

    r = api.get("/api/v1/company/profile")
    if r.status_code == 200:
        d = r.json()
        ok("公司資料", f"name={d.get('name','?')} plan={d.get('plan','?')}")
    else:
        fail("公司資料", f"HTTP {r.status_code}")

    r = api.get("/api/v1/company/quota")
    if r.status_code == 200:
        ok("配額狀態")
    else:
        fail("配額狀態", f"HTTP {r.status_code}")

    r = api.get("/api/v1/company/users")
    if r.status_code == 200:
        members = r.json()
        cnt = len(members) if isinstance(members, list) else len(members.get("users", []))
        ok("成員清單", f"{cnt} 位")
    else:
        fail("成員清單", f"HTTP {r.status_code}")

    r = api.get("/api/v1/company/usage/summary")
    if r.status_code == 200:
        ok("用量摘要")
    else:
        fail("用量摘要", f"HTTP {r.status_code}")

    r = api.get("/api/v1/company/usage/by-user")
    if r.status_code == 200:
        rows = r.json()
        cnt = len(rows) if isinstance(rows, list) else 0
        ok("按使用者用量", f"{cnt} 筆")
    else:
        fail("按使用者用量", f"HTTP {r.status_code}")


# ════════════════════════════════════════════════════════════════════════════════
# Phase 10 ─ 功能旗標管理
# ════════════════════════════════════════════════════════════════════════════════
def phase10():
    section("P10 功能旗標管理")

    r = api.get("/api/v1/feature-flags/")
    if r.status_code == 200:
        flags = r.json()
        cnt = len(flags) if isinstance(flags, list) else len(flags.get("flags", []))
        ok("功能旗標清單", f"{cnt} 筆")
    else:
        fail("功能旗標清單", f"HTTP {r.status_code}")
        return

    flag_key = "test_auto_flag_" + datetime.datetime.now().strftime("%H%M%S")
    r = api.post("/api/v1/feature-flags/", {
        "key": flag_key,
        "name": "自動測試功能旗標",
        "description": "由自動測試腳本建立",
        "enabled": True,
    })
    flag_created = False
    if r.status_code in (200, 201):
        flag_created = True
        ok("建立功能旗標", f"key={flag_key}")
    elif r.status_code == 409:
        ok("功能旗標已存在")
    else:
        fail("建立功能旗標", f"HTTP {r.status_code} {r.text[:100]}")

    if flag_created:
        # feature-flags use key as URL param, not id
        r = api.put(f"/api/v1/feature-flags/{flag_key}", {"enabled": False})
        if r.status_code == 200:
            ok("停用功能旗標")
        else:
            fail("停用功能旗標", f"HTTP {r.status_code}")

        r = api.delete(f"/api/v1/feature-flags/{flag_key}")
        if r.status_code in (200, 204):
            ok("刪除功能旗標")
        else:
            fail("刪除功能旗標", f"HTTP {r.status_code}")


# ════════════════════════════════════════════════════════════════════════════════
# Phase 11 ─ 對話分析 + 稽核日誌
# ════════════════════════════════════════════════════════════════════════════════
def phase11():
    section("P11 對話分析 + 稽核日誌")

    for path, label in [
        ("/api/v1/chat/analytics/summary",              "分析摘要"),
        ("/api/v1/chat/analytics/trend",                "對話趨勢"),
        ("/api/v1/chat/analytics/top-queries",          "熱門問題"),
        ("/api/v1/chat/analytics/unanswered",           "未答問題"),
    ]:
        r = api.get(path, params={"limit": 10, "days": 7})
        if r.status_code == 200:
            raw = r.json()
            cnt = len(raw) if isinstance(raw, list) else len(raw.get("queries", raw.get("items", [])))
            ok(label, f"{cnt} 筆" if cnt else "")
        else:
            fail(label, f"HTTP {r.status_code}")

    r = api.get("/api/v1/audit/logs", params={"limit": 10})
    if r.status_code == 200:
        raw = r.json()
        items = raw if isinstance(raw, list) else raw.get("logs", raw.get("items", []))
        ok("稽核日誌", f"{len(items)} 筆")
    else:
        fail("稽核日誌", f"HTTP {r.status_code}")

    r = api.get("/api/v1/audit/logs/export", params={"format": "csv"})
    if r.status_code == 200:
        ok("稽核日誌 CSV 匯出", f"{len(r.content)} bytes")
    else:
        fail("稽核日誌 CSV 匯出", f"HTTP {r.status_code}")

    for path, label in [
        ("/api/v1/audit/usage/summary",   "稽核 - 用量摘要"),
        ("/api/v1/audit/usage/by-action", "稽核 - 按動作"),
    ]:
        r = api.get(path)
        if r.status_code == 200:
            ok(label)
        else:
            fail(label, f"HTTP {r.status_code}")


# ════════════════════════════════════════════════════════════════════════════════
# Phase 12 ─ Agent 資料夾監控
# ════════════════════════════════════════════════════════════════════════════════
def phase12():
    section("P12 Agent 資料夾監控")

    watch_path = AGENT_WATCH_CONTAINER
    host_path_obj = Path(AGENT_WATCH_HOST)
    host_files = list(host_path_obj.glob("*")) if host_path_obj.exists() else []
    print(f"  ℹ️  監控路徑（容器）: {watch_path}")
    print(f"  ℹ️  本機對應: {AGENT_WATCH_HOST}  ({len(host_files)} 個檔案)")

    # Agent 狀態
    r = api.get("/api/v1/agent/status")
    if r.status_code == 200:
        st = r.json()
        ok("Agent 狀態",
           f"watcher={st.get('watcher_running')} "
           f"scheduler={st.get('scheduler_running')} "
           f"folders={st.get('active_folders')} "
           f"pending={st.get('pending_review_count')}")
    else:
        fail("Agent 狀態", f"HTTP {r.status_code}")

    # 監控資料夾清單
    r = api.get("/api/v1/agent/folders")
    if r.status_code == 200:
        folders = r.json()
        ok("監控資料夾清單", f"{len(folders) if isinstance(folders, list) else 0} 筆")
    else:
        fail("監控資料夾清單", f"HTTP {r.status_code}")

    # 目錄瀏覽 API
    r = api.get("/api/v1/agent/browse", params={"path": "/code"})
    if r.status_code == 200:
        dirs = r.json().get("dirs", [])
        ok("瀏覽目錄 /code", f"{len(dirs)} 個子目錄")
    else:
        fail("瀏覽目錄 /code", f"HTTP {r.status_code}")

    # 新增或確認監控資料夾
    folder_id = None
    r_list = api.get("/api/v1/agent/folders")
    if r_list.status_code == 200:
        for f in (r_list.json() or []):
            if f.get("folder_path") == watch_path:
                folder_id = f.get("id")
                break

    if not folder_id:
        r = api.post("/api/v1/agent/folders", {
            "folder_path": watch_path,
            "display_name": "HR規章文件（自動測試）",
            "recursive": True,
            "max_depth": 2,
            "default_category": "hr-regulations",
        })
        if r.status_code in (200, 201):
            folder_id = r.json().get("id")
            ok("新增監控資料夾", f"path={watch_path}")
        elif r.status_code == 409:
            ok("監控資料夾已存在")
        else:
            fail("新增監控資料夾", f"HTTP {r.status_code} {r.text[:100]}")
    else:
        ok("監控資料夾已存在", f"id={str(folder_id)[:8]}...")

    # Scan Preview（Ollama 摘要）
    if host_files:
        file_names = [f.name for f in host_files if f.is_file()][:10]
        samples = []
        for fp in [f for f in host_files if f.is_file() and f.suffix == ".md"][:2]:
            try:
                samples.append(fp.read_text(encoding="utf-8", errors="ignore")[:800])
            except Exception:
                pass

        r = api.post("/api/v1/agent/scan-preview", {
            "subfolders": [{
                "path": watch_path,
                "name": "test-agent-watch",
                "files": file_names,
                "content_samples": samples,
            }]
        }, timeout=120)
        if r.status_code == 200:
            sub = (r.json().get("subfolders") or [{}])[0]
            ok("Scan Preview（Ollama 摘要）", sub.get("summary", "")[:60])
        else:
            fail("Scan Preview", f"HTTP {r.status_code} {r.text[:100]}")

    # 啟動 Agent
    r = api.post("/api/v1/agent/start")
    if r.status_code == 200:
        ok("啟動 Agent")
    else:
        fail("啟動 Agent", f"HTTP {r.status_code} {r.text[:80]}")

    # 手動觸發掃描
    r = api.post("/api/v1/agent/scan")
    if r.status_code == 200:
        ok("觸發即時掃描")
    else:
        fail("觸發即時掃描", f"HTTP {r.status_code} {r.text[:80]}")

    # 等待審核項目出現
    print("  ⏳ 等待掃描結果（最多 30 秒）...")
    for _ in range(6):
        time.sleep(5)
        r = api.get("/api/v1/agent/review", params={"limit": 5})
        if r.status_code == 200 and r.json().get("total", 0) > 0:
            break

    # 審核佇列操作
    r = api.get("/api/v1/agent/review", params={"limit": 20, "status_filter": "pending"})
    if r.status_code == 200:
        data = r.json()
        items = data.get("items", [])
        total = data.get("total", len(items))
        ok("審核佇列（待審核）", f"total={total} 筆")

        if items:
            # 核准第一筆
            fid = items[0]["id"]
            r2 = api.post(f"/api/v1/agent/review/{fid}/approve")
            (ok if r2.status_code == 200 else fail)("核准審核項目", f"id={str(fid)[:8]}")

            # 拒絕第二筆
            if len(items) >= 2:
                sid = items[1]["id"]
                r2 = api.post(f"/api/v1/agent/review/{sid}/reject", {"reason": "自動測試拒絕"})
                (ok if r2.status_code == 200 else fail)("拒絕審核項目", f"id={str(sid)[:8]}")

            # 修改分類並確認第三筆
            if len(items) >= 3:
                tid_ = items[2]["id"]
                r2 = api.post(f"/api/v1/agent/review/{tid_}/modify", {
                    "category": "人事管理",
                    "note": "自動測試修改分類",
                })
                (ok if r2.status_code == 200 else fail)("修改分類並確認", f"id={str(tid_)[:8]}")

            # 批量核准其餘
            remaining = [it["id"] for it in items[3:6]]
            if remaining:
                r2 = api.post("/api/v1/agent/review/batch-approve", {"item_ids": remaining})
                (ok if r2.status_code == 200 else fail)(
                    "批量核准剩餘",
                    f"{r2.json().get('approved_count', 0)} 筆" if r2.status_code == 200 else r2.text[:60],
                )
    else:
        fail("審核佇列", f"HTTP {r.status_code}")

    # 批次狀態摘要
    r = api.get("/api/v1/agent/batches")
    if r.status_code == 200:
        ok("批次狀態統計", str(r.json())[:80])
    else:
        fail("批次狀態統計", f"HTTP {r.status_code}")

    # 批次報告 PDF
    r = api.get("/api/v1/agent/batches/report")
    if r.status_code == 200 and len(r.content) > 100:
        ok("批次報告 PDF", f"{len(r.content)} bytes")
    else:
        fail("批次報告 PDF", f"HTTP {r.status_code} size={len(r.content) if r.content else 0}")

    # Toggle 資料夾
    if folder_id:
        r = api.patch(f"/api/v1/agent/folders/{folder_id}/toggle")
        if r.status_code == 200:
            state = r.json().get("is_active")
            ok("Toggle 監控資料夾（停用）", f"is_active={state}")
            # 還原為啟用
            api.patch(f"/api/v1/agent/folders/{folder_id}/toggle")
        else:
            fail("Toggle 監控資料夾", f"HTTP {r.status_code}")

    # 停止 Agent
    r = api.post("/api/v1/agent/stop")
    if r.status_code == 200:
        ok("停止 Agent")
    else:
        fail("停止 Agent", f"HTTP {r.status_code}")


# ════════════════════════════════════════════════════════════════════════════════
# Phase 13 ─ 效能抽樣
# ════════════════════════════════════════════════════════════════════════════════
def phase13():
    section("P13 效能抽樣（非 LLM 端點 SLA）")

    perf_cases = [
        ("/health",                             "GET",  None,                   3,  "健康檢查"),
        ("/api/v1/kb/stats",                    "GET",  None,                   2,  "KB 統計"),
        ("/api/v1/kb/search",                   "POST", {"query": "年假", "top_k": 5}, 5, "KB 搜尋"),
        ("/api/v1/chat/analytics/summary",      "GET",  None,                   5,  "分析摘要"),
        ("/api/v1/audit/logs",                  "GET",  None,                   5,  "稽核日誌"),
        ("/api/v1/departments/tree",            "GET",  None,                   3,  "部門樹"),
        ("/api/v1/kb-maintenance/kb/health",    "GET",  None,                   5,  "KB 健康"),
    ]

    times = []
    for path, method, body, sla, label in perf_cases:
        t0 = time.time()
        r = api.get(path) if method == "GET" else api.post(path, body)
        elapsed = time.time() - t0
        times.append(elapsed)
        (ok if elapsed <= sla else fail)(
            f"效能：{label}",
            f"{elapsed:.2f}s  (SLA={sla}s)",
        )

    avg = sum(times) / len(times)
    print(f"\n  📊 平均 API 回應: {avg:.2f}s")


# ════════════════════════════════════════════════════════════════════════════════
# 報告儲存
# ════════════════════════════════════════════════════════════════════════════════
def save_report():
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = ENCLAVE_ROOT / "test-results" / f"enclave_test_{ts}.json"
    out.parent.mkdir(exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": ts,
            "summary": {"passed": passed, "failed": failed, "skipped": skipped},
            "results": results_log,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n  📄 測試報告: {out}")


# ════════════════════════════════════════════════════════════════════════════════
# 主程式
# ════════════════════════════════════════════════════════════════════════════════
PHASE_FN = {
    0:  (phase0,  {}),
    1:  (phase1,  {}),
    2:  (phase2,  {}),
    3:  (phase3,  {}),
    4:  (phase4,  {}),
    5:  (phase5,  {}),
    6:  (phase6,  {}),
    7:  (phase7,  {}),
    8:  (phase8,  {}),
    9:  (phase9,  {}),
    10: (phase10, {}),
    11: (phase11, {}),
    12: (phase12, {}),
    13: (phase13, {}),
}


def main():
    parser = argparse.ArgumentParser(description="Enclave 完整功能測試")
    parser.add_argument("--phase", type=int, action="append", dest="phases",
                        help="只跑指定 phase (可重複)，例: --phase 12 --phase 3")
    parser.add_argument("--skip-upload", action="store_true", help="跳過文件上傳 (P1)")
    args = parser.parse_args()

    t0 = time.time()
    print(f"\n{BOLD}{'═'*60}{RESET}")
    print(f"{BOLD}  Enclave 功能測試  {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{RESET}")
    print(f"{BOLD}{'═'*60}{RESET}")
    print(f"  目標: {BASE_URL}")

    run_phases = sorted(set(args.phases)) if args.phases else list(range(14))

    # P0 始終先執行（取得 token）
    phase0()
    PHASE_FN[1] = (phase1, {"skip_upload": args.skip_upload})

    skip_p0 = 0 in run_phases
    for pid in run_phases:
        if pid == 0 and skip_p0:
            continue  # 已執行
        fn, kwargs = PHASE_FN[pid]
        try:
            if pid == 3:
                conv_id = fn(**kwargs)
                PHASE_FN[4] = (phase4, {"conv_id": conv_id})
            else:
                fn(**kwargs)
        except Exception as e:
            fail(f"Phase {pid} 例外", str(e)[:120])
            traceback.print_exc()

    elapsed = time.time() - t0
    total = passed + failed + skipped
    pass_rate = round(passed / (total - skipped) * 100, 1) if (total - skipped) > 0 else 0

    print(f"\n{BOLD}{'═'*60}{RESET}")
    print(f"{BOLD}  完成  耗時 {elapsed:.0f}s{RESET}")
    print(f"  {GREEN}通過: {passed}{RESET}  {RED}失敗: {failed}{RESET}  {YELLOW}略過: {skipped}{RESET}")
    print(f"  通過率: {pass_rate}%  ({passed}/{total - skipped})")
    print(f"{BOLD}{'═'*60}{RESET}")

    save_report()

    if failed:
        print(f"\n{RED}失敗項目：{RESET}")
        for r in results_log:
            if r["status"] == "FAIL":
                print(f"  ✗ {r['label']}  {r.get('detail','')}")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
