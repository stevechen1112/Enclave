#!/usr/bin/env python3
"""
Enclave Flow 7：分析 & 稽核全流程測試
========================================
覆蓋 Audit Logs / Usage Stats / Export / Chat Analytics /
     RAG Dashboard / Feedback Stats / KB Stats / Platform Analytics 管道。

測試項目：
  T7-01  GET  /audit/logs — 稽核日誌
  T7-02  GET  /audit/usage/summary — 使用量摘要
  T7-03  GET  /audit/usage/by-action — 按動作分類
  T7-04  GET  /audit/usage/me/summary — 個人使用量
  T7-05  GET  /audit/usage/me/by-action — 個人按動作分類
  T7-06  GET  /audit/usage/records — 使用紀錄明細
  T7-07  GET  /audit/logs/export?format=csv — 匯出稽核 CSV
  T7-08  GET  /audit/usage/export?format=csv — 匯出使用量 CSV
  T7-09  GET  /chat/conversations/search — 對話搜尋
  T7-10  GET  /chat/conversations/{id}/export — 匯出對話 Markdown
  T7-11  GET  /chat/feedback/stats — 回饋統計
  T7-12  GET  /chat/dashboard/rag — RAG 品質儀表板
  T7-13  GET  /chat/analytics/summary — 查詢分析摘要
  T7-14  GET  /chat/analytics/trend — 每日查詢趨勢
  T7-15  GET  /chat/analytics/top-queries — 熱門查詢
  T7-16  GET  /chat/analytics/unanswered — 未回答查詢
  T7-17  GET  /kb/stats — 知識庫統計
  T7-18  GET  /kb/search — KB 語意搜尋
  T7-19  GET  /analytics/trends/daily — 平台每日趨勢
  T7-20  GET  /analytics/anomalies — 異常偵測
  T7-21  GET  /analytics/budget-alerts — 預算警示
  T7-22  POST /chat/chat — 產生測試數據
  T7-23  GET  /company/usage/by-user — 用戶使用量

用法：
  python scripts/test_flow7_analytics_audit.py
  python scripts/test_flow7_analytics_audit.py --keep
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import requests

# Windows cp950 workaround: force UTF-8 stdout
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ── UI ─────────────────────────────────────────
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

passed = 0
failed = 0
skipped = 0


def ok(name: str, detail: str = "") -> None:
    global passed
    passed += 1
    msg = f"  {GREEN}✔ {name}{RESET}"
    if detail:
        msg += f"  {DIM}({detail}){RESET}"
    print(msg)


def fail(name: str, detail: str = "") -> None:
    global failed
    failed += 1
    msg = f"  {RED}✘ {name}{RESET}"
    if detail:
        msg += f"  {DIM}({detail}){RESET}"
    print(msg)


def skip(name: str, reason: str = "") -> None:
    global skipped
    skipped += 1
    print(f"  {YELLOW}⊘ {name} — SKIP: {reason}{RESET}")


def section(title: str):
    print(f"\n{BOLD}{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}{RESET}")


def _assert(condition: bool, name: str, detail: str = "") -> bool:
    if condition:
        ok(name, detail)
    else:
        fail(name, detail)
    return condition


# ── API Client ─────────────────────────────────
class ApiClient:
    def __init__(self, base_url: str, user: str, password: str):
        self.base = base_url
        self.session = requests.Session()
        r = self.session.post(
            f"{self.base}/api/v1/auth/login/access-token",
            data={"username": user, "password": password},
            timeout=10,
        )
        r.raise_for_status()
        token = r.json()["access_token"]
        self.session.headers["Authorization"] = f"Bearer {token}"

    def get(self, path: str, **kwargs) -> requests.Response:
        return self.session.get(f"{self.base}/api/v1{path}", timeout=15, **kwargs)

    def post(self, path: str, json_data=None, **kwargs) -> requests.Response:
        return self.session.post(f"{self.base}/api/v1{path}", json=json_data, timeout=30, **kwargs)

    def delete(self, path: str, **kwargs) -> requests.Response:
        return self.session.delete(f"{self.base}/api/v1{path}", timeout=15, **kwargs)


# ══════════════════════════════════════════════════
#  Tests
# ══════════════════════════════════════════════════
def run_tests(api: ApiClient, keep: bool):
    conversation_id: str | None = None
    doc_id: str | None = None

    # ── Phase 0: 產生測試數據 ────────────
    section("Phase 0: 產生測試數據（上傳 + 對話）")

    # 上傳一個文件，確保 KB 有內容
    tmp = tempfile.NamedTemporaryFile(suffix=".md", prefix="flow7_", delete=False, mode="w", encoding="utf-8")
    tmp.write("# Flow7 測試文件\n\n公司差旅報帳需在五日內完成。\n出差交通費依實際支出核銷。\n")
    tmp.close()
    try:
        with open(tmp.name, "rb") as fh:
            r = api.session.post(
                f"{api.base}/api/v1/documents/upload",
                files={"file": ("flow7_test.md", fh)},
                timeout=30,
            )
        if r.status_code == 200:
            doc_id = r.json().get("id")
            # 等待處理完成
            deadline = time.time() + 60
            while time.time() < deadline:
                r2 = api.get(f"/documents/{doc_id}")
                if r2.status_code == 200 and r2.json().get("status") in ("completed", "failed"):
                    break
                time.sleep(3)
            ok("文件上傳 & 處理完成", f"doc_id={doc_id}")
        else:
            print(f"  {DIM}上傳失敗 HTTP {r.status_code}，部分測試將使用既有數據{RESET}")
    finally:
        os.unlink(tmp.name)

    # T7-22: 產生一次對話，確保有 conversation
    r = api.post("/chat/chat", json_data={
        "question": "公司差旅報帳的期限是多久？",
        "top_k": 3,
    })
    if _assert(r.status_code == 200, "T7-22 產生測試對話", f"HTTP {r.status_code}"):
        body = r.json()
        conversation_id = body.get("conversation_id")
        print(f"      {DIM}conversation_id={conversation_id}{RESET}")

    # ── Phase 1: 稽核日誌 ───────────────
    section("Phase 1: 稽核日誌")

    # T7-01: audit logs
    r = api.get("/audit/logs", params={"limit": 10})
    if _assert(r.status_code == 200, "T7-01 稽核日誌列表", f"HTTP {r.status_code}"):
        logs = r.json()
        _assert(isinstance(logs, list), "T7-01b 回傳陣列", f"count={len(logs)}")
        if logs:
            print(f"      {DIM}最新: action={logs[0].get('action')}, user={logs[0].get('user_email')}{RESET}")

    # T7-02: usage summary
    r = api.get("/audit/usage/summary")
    if _assert(r.status_code == 200, "T7-02 使用量摘要", f"HTTP {r.status_code}"):
        summary = r.json()
        print(f"      {DIM}{json.dumps(summary, ensure_ascii=False)[:100]}{RESET}")

    # T7-03: usage by action
    r = api.get("/audit/usage/by-action")
    _assert(r.status_code == 200, "T7-03 按動作分類", f"HTTP {r.status_code}")

    # T7-04: personal usage
    r = api.get("/audit/usage/me/summary")
    _assert(r.status_code == 200, "T7-04 個人使用量摘要", f"HTTP {r.status_code}")

    # T7-05: personal by action
    r = api.get("/audit/usage/me/by-action")
    _assert(r.status_code == 200, "T7-05 個人按動作分類", f"HTTP {r.status_code}")

    # T7-06: usage records
    r = api.get("/audit/usage/records", params={"limit": 10})
    if _assert(r.status_code == 200, "T7-06 使用紀錄明細", f"HTTP {r.status_code}"):
        records = r.json()
        _assert(isinstance(records, list), "T7-06b 回傳陣列", f"count={len(records)}")

    # ── Phase 2: 匯出 ───────────────────
    section("Phase 2: 稽核匯出")

    # T7-07: export audit logs CSV
    r = api.get("/audit/logs/export", params={"format": "csv"})
    if _assert(r.status_code == 200, "T7-07 匯出稽核 CSV", f"HTTP {r.status_code}"):
        ct = r.headers.get("Content-Type", "")
        _assert("csv" in ct or "text" in ct or "octet" in ct, "T7-07b Content-Type", ct[:60])
        _assert(len(r.content) > 0, "T7-07c 有內容", f"{len(r.content)} bytes")

    # T7-08: export usage CSV
    r = api.get("/audit/usage/export", params={"format": "csv"})
    if _assert(r.status_code == 200, "T7-08 匯出使用量 CSV", f"HTTP {r.status_code}"):
        _assert(len(r.content) > 0, "T7-08b 有內容", f"{len(r.content)} bytes")

    # ── Phase 3: Chat 分析 ──────────────
    section("Phase 3: Chat 分析 & 回饋")

    # T7-09: conversation search
    r = api.get("/chat/conversations/search", params={"q": "報帳"})
    _assert(r.status_code == 200, "T7-09 對話搜尋", f"HTTP {r.status_code}")

    # T7-10: export conversation
    if conversation_id:
        r = api.get(f"/chat/conversations/{conversation_id}/export", params={"format": "markdown"})
        if _assert(r.status_code == 200, "T7-10 匯出對話 Markdown", f"HTTP {r.status_code}"):
            ct = r.headers.get("Content-Type", "")
            _assert(len(r.content) > 0, "T7-10b 有內容", f"{len(r.content)} bytes")
    else:
        skip("T7-10 匯出對話", "無 conversation_id")

    # T7-11: feedback stats
    r = api.get("/chat/feedback/stats")
    _assert(r.status_code == 200, "T7-11 回饋統計", f"HTTP {r.status_code}")

    # T7-12: RAG dashboard
    r = api.get("/chat/dashboard/rag", params={"days": 30})
    if _assert(r.status_code == 200, "T7-12 RAG 品質儀表板", f"HTTP {r.status_code}"):
        rag = r.json()
        print(f"      {DIM}{json.dumps(rag, ensure_ascii=False)[:120]}{RESET}")

    # T7-13: analytics summary
    r = api.get("/chat/analytics/summary", params={"days": 30})
    if _assert(r.status_code == 200, "T7-13 查詢分析摘要", f"HTTP {r.status_code}"):
        summary = r.json()
        print(f"      {DIM}total_queries={summary.get('total_queries')}{RESET}")

    # T7-14: trend
    r = api.get("/chat/analytics/trend", params={"days": 7})
    if _assert(r.status_code == 200, "T7-14 每日查詢趨勢", f"HTTP {r.status_code}"):
        trend = r.json()
        _assert(isinstance(trend, list), "T7-14b 回傳陣列", f"days={len(trend)}")

    # T7-15: top queries
    r = api.get("/chat/analytics/top-queries", params={"days": 30, "limit": 10})
    _assert(r.status_code == 200, "T7-15 熱門查詢", f"HTTP {r.status_code}")

    # T7-16: unanswered
    r = api.get("/chat/analytics/unanswered", params={"days": 30, "limit": 10})
    _assert(r.status_code == 200, "T7-16 未回答查詢", f"HTTP {r.status_code}")

    # ── Phase 4: KB ─────────────────────
    section("Phase 4: 知識庫統計")

    # T7-17: KB stats
    r = api.get("/kb/stats")
    if _assert(r.status_code == 200, "T7-17 KB 統計", f"HTTP {r.status_code}"):
        stats = r.json()
        print(f"      {DIM}{json.dumps(stats, ensure_ascii=False)[:120]}{RESET}")

    # T7-18: KB search
    r = api.post("/kb/search", json_data={"query": "報帳流程", "top_k": 3})
    if _assert(r.status_code == 200, "T7-18 KB 語意搜尋", f"HTTP {r.status_code}"):
        results = r.json().get("results", [])
        print(f"      {DIM}results={len(results)}{RESET}")

    # ── Phase 5: 平台分析 ───────────────
    section("Phase 5: 平台分析（Analytics）")

    # T7-19: daily trends
    r = api.get("/analytics/trends/daily", params={"days": 7})
    _assert(r.status_code == 200, "T7-19 平台每日趨勢", f"HTTP {r.status_code}")

    # T7-20: anomalies
    r = api.get("/analytics/anomalies")
    _assert(r.status_code == 200, "T7-20 異常偵測", f"HTTP {r.status_code}")

    # T7-21: budget alerts
    r = api.get("/analytics/budget-alerts")
    _assert(r.status_code == 200, "T7-21 預算警示", f"HTTP {r.status_code}")

    # T7-23: company usage by user
    r = api.get("/company/usage/by-user")
    _assert(r.status_code == 200, "T7-23 用戶使用量", f"HTTP {r.status_code}")

    # ── Phase 6: 清理 ───────────────────
    section("Phase 6: 清理")

    if keep:
        print(f"  {YELLOW}--keep 模式，跳過刪除{RESET}")
    else:
        if conversation_id:
            r = api.delete(f"/chat/conversations/{conversation_id}")
            ok("對話清理完成") if r.status_code == 200 else None
        if doc_id:
            r = api.delete(f"/documents/{doc_id}")
            ok("文件清理完成") if r.status_code == 200 else None


def main():
    parser = argparse.ArgumentParser(description="Enclave Flow 7 — 分析 & 稽核全流程測試")
    parser.add_argument("--base-url", default="http://localhost:8001")
    parser.add_argument("--user", default="admin@example.com")
    parser.add_argument("--password", default="admin123")
    parser.add_argument("--keep", action="store_true", help="保留測試資料不刪除")
    args = parser.parse_args()

    print(f"\n{BOLD}═══════════════════════════════════════════════════")
    print(f"  Enclave Flow 7：分析 & 稽核全流程測試")
    print(f"  Target: {args.base_url}")
    print(f"═══════════════════════════════════════════════════{RESET}")

    try:
        api = ApiClient(args.base_url, args.user, args.password)
        ok("登入成功")
    except Exception as e:
        fail(f"登入失敗: {e}")
        sys.exit(1)

    run_tests(api, keep=args.keep)

    section("結果摘要")
    total = passed + failed + skipped
    print(f"  {GREEN}通過: {passed}{RESET}  {RED}失敗: {failed}{RESET}  {YELLOW}跳過: {skipped}{RESET}  總計: {total}")
    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
