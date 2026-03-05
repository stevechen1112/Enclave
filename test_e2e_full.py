#!/usr/bin/env python3
"""
Enclave E2E 測試腳本 — 完整 pipeline 驗證
==========================================
測試範圍：
  1. 登入 / 取得 token
  2. 取得支援格式清單
  3. 上傳多種格式本地檔案（txt, md, csv, pdf）
  4. 輪詢文件狀態直到 completed / failed
  5. 語意搜尋（KB search）驗證 embedding 品質
  6. 清理測試文件

用法：
  python test_e2e_full.py                         # 預設 localhost:8001
  python test_e2e_full.py --base-url http://x:8001
  python test_e2e_full.py --keep                  # 不刪除測試文件
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

# ── 顏色輸出 ─────────────────────────────────────
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def ok(msg: str) -> None:
    print(f"  {GREEN}✔ {msg}{RESET}")


def fail(msg: str) -> None:
    print(f"  {RED}✘ {msg}{RESET}")


def info(msg: str) -> None:
    print(f"  {CYAN}ℹ {msg}{RESET}")


def section(title: str) -> None:
    print(f"\n{BOLD}{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}{RESET}")


# ── 設定 ─────────────────────────────────────────
TEST_DATA_DIR = Path(__file__).resolve().parent / "test-data" / "company-documents"

# 要測試的本地檔案（相對於 TEST_DATA_DIR）
TEST_FILES: List[Dict[str, Any]] = [
    {
        "path": "sop/新人到職SOP.md",
        "search_query": "新人到職報到流程",
        "expect_min_chunks": 1,
    },
    {
        "path": "hr-regulations/員工手冊-第一章-總則.md",
        "search_query": "員工出勤規範",
        "expect_min_chunks": 1,
    },
    {
        "path": "contracts/勞動契約書-謝雅玲.txt",
        "search_query": "勞動契約薪資試用期",
        "expect_min_chunks": 1,
    },
    {
        "path": "employee-data/員工名冊.csv",
        "search_query": "員工名冊部門電話",
        "expect_min_chunks": 1,
    },
    {
        "path": "sop/報帳作業規範.pdf",
        "search_query": "報帳流程發票收據核銷",
        "expect_min_chunks": 1,
    },
]

# 搜尋用的查詢（測試語意搜尋品質）
SEARCH_QUERIES = [
    {"query": "加班費如何計算", "expect_results": True},
    {"query": "新人報到第一天需要做什麼", "expect_results": True},
    {"query": "quantum physics dark matter", "expect_results": False},  # 不相關
]

# ── 測試類別 ─────────────────────────────────────

class E2ETestRunner:
    def __init__(self, base_url: str, username: str, password: str, keep: bool = False):
        self.base_url = base_url.rstrip("/")
        self.api = f"{self.base_url}/api/v1"
        self.username = username
        self.password = password
        self.keep = keep
        self.token: Optional[str] = None
        self.headers: Dict[str, str] = {}
        self.uploaded_ids: List[str] = []
        self.passed = 0
        self.failed = 0
        self.skipped = 0

    def _assert(self, condition: bool, pass_msg: str, fail_msg: str) -> bool:
        if condition:
            ok(pass_msg)
            self.passed += 1
        else:
            fail(fail_msg)
            self.failed += 1
        return condition

    # ── 1. 登入 ──────────────────────────────────

    def test_login(self) -> bool:
        section("1. 登入認證")
        try:
            r = requests.post(
                f"{self.api}/auth/login/access-token",
                data={"username": self.username, "password": self.password},
                timeout=10,
            )
            if not self._assert(
                r.status_code == 200,
                f"登入成功 (HTTP {r.status_code})",
                f"登入失敗 (HTTP {r.status_code}): {r.text[:200]}",
            ):
                return False

            data = r.json()
            self.token = data.get("access_token")
            self.headers = {"Authorization": f"Bearer {self.token}"}
            self._assert(
                bool(self.token),
                f"Token 取得成功 ({self.token[:20]}...)",
                "Token 為空",
            )
            return True
        except Exception as e:
            fail(f"連線失敗: {e}")
            self.failed += 1
            return False

    # ── 2. 支援格式 ──────────────────────────────

    def test_supported_formats(self) -> None:
        section("2. 支援格式端點")
        r = requests.get(f"{self.api}/documents/supported-formats", headers=self.headers, timeout=10)
        self._assert(r.status_code == 200, f"GET /supported-formats → {r.status_code}", f"格式端點失敗: {r.status_code}")

        formats = r.json()
        if isinstance(formats, dict):
            all_exts = []
            for exts in formats.values():
                all_exts.extend(exts)
            self._assert(len(all_exts) > 5, f"共 {len(all_exts)} 種副檔名", "副檔名太少")
            info(f"格式分類: {list(formats.keys())}")
        elif isinstance(formats, list):
            self._assert(len(formats) > 5, f"共 {len(formats)} 個格式", "格式太少")

    # ── 3. 文件上傳 ──────────────────────────────

    def test_upload_files(self) -> None:
        section("3. 上傳本地檔案")
        for entry in TEST_FILES:
            rel_path = entry["path"]
            full_path = TEST_DATA_DIR / rel_path
            if not full_path.exists():
                info(f"跳過：{rel_path} (檔案不存在)")
                self.skipped += 1
                continue

            filename = full_path.name
            file_size = full_path.stat().st_size
            with open(full_path, "rb") as f:
                files = {"file": (filename, f, "application/octet-stream")}
                r = requests.post(
                    f"{self.api}/documents/upload",
                    headers=self.headers,
                    files=files,
                    timeout=30,
                )

            if self._assert(
                r.status_code == 200,
                f"上傳 {filename} ({file_size:,} bytes) → HTTP {r.status_code}",
                f"上傳 {filename} 失敗: HTTP {r.status_code} — {r.text[:200]}",
            ):
                doc = r.json()
                doc_id = doc.get("id")
                status = doc.get("status")
                info(f"  doc_id={doc_id}, status={status}")
                self.uploaded_ids.append(doc_id)
                entry["doc_id"] = doc_id
            else:
                entry["doc_id"] = None

    # ── 4. 等待處理完成 ──────────────────────────

    def test_processing(self, timeout_sec: int = 120, poll_interval: int = 5) -> None:
        section("4. 等待文件處理 (parse → chunk → embed)")
        pending = {e["doc_id"] for e in TEST_FILES if e.get("doc_id")}
        if not pending:
            info("無文件需等待")
            return

        info(f"等待 {len(pending)} 個文件完成（上限 {timeout_sec}s）")
        start = time.time()
        completed = set()
        failed_docs = set()

        while pending and (time.time() - start) < timeout_sec:
            time.sleep(poll_interval)
            elapsed = int(time.time() - start)
            for doc_id in list(pending):
                try:
                    r = requests.get(f"{self.api}/documents/{doc_id}", headers=self.headers, timeout=10)
                    doc = r.json()
                    status = doc.get("status")
                    chunks = doc.get("chunk_count")
                    error = doc.get("error_message")

                    if status == "completed":
                        ok(f"[{elapsed}s] {doc.get('filename')} → completed, {chunks} chunks")
                        completed.add(doc_id)
                        pending.discard(doc_id)
                    elif status == "failed":
                        fail(f"[{elapsed}s] {doc.get('filename')} → failed: {error}")
                        failed_docs.add(doc_id)
                        pending.discard(doc_id)
                    else:
                        info(f"[{elapsed}s] {doc.get('filename')} → {status}")
                except Exception as e:
                    info(f"[{elapsed}s] 查詢 {doc_id[:8]}... 失敗: {e}")

        # 統計
        for doc_id in completed:
            self.passed += 1
        for doc_id in failed_docs:
            self.failed += 1
        for doc_id in pending:
            fail(f"超時：{doc_id[:8]}... 仍在處理中")
            self.failed += 1

        # 驗證 chunk 數量
        for entry in TEST_FILES:
            doc_id = entry.get("doc_id")
            if doc_id and doc_id in completed:
                r = requests.get(f"{self.api}/documents/{doc_id}", headers=self.headers, timeout=10)
                doc = r.json()
                chunk_count = doc.get("chunk_count", 0)
                min_chunks = entry.get("expect_min_chunks", 1)
                self._assert(
                    chunk_count >= min_chunks,
                    f"{doc.get('filename')}: {chunk_count} chunks (≥ {min_chunks})",
                    f"{doc.get('filename')}: chunks={chunk_count}, 預期 ≥ {min_chunks}",
                )

    # ── 5. 語意搜尋 ──────────────────────────────

    def test_semantic_search(self) -> None:
        section("5. 語意搜尋 (KB Search)")

        # 先用文件關聯的查詢測試
        for entry in TEST_FILES:
            query = entry.get("search_query")
            doc_id = entry.get("doc_id")
            if not query or not doc_id:
                continue

            r = requests.post(
                f"{self.api}/kb/search",
                headers=self.headers,
                json={"query": query, "top_k": 5},
                timeout=30,
            )
            if r.status_code != 200:
                fail(f"搜尋 '{query[:20]}...' 失敗: HTTP {r.status_code}")
                self.failed += 1
                continue

            data = r.json()
            results = data.get("results", [])
            total = data.get("total_results", 0)

            # 檢查對應文件是否在結果中
            matched = any(
                r.get("document_id") == doc_id for r in results
            )
            self._assert(
                matched,
                f"搜尋 '{query[:25]}' → 找到對應文件 (共 {total} 結果)",
                f"搜尋 '{query[:25]}' → 未找到對應文件 (共 {total} 結果)",
            )

        # 不相關查詢測試
        for sq in SEARCH_QUERIES:
            query = sq["query"]
            expect = sq["expect_results"]
            r = requests.post(
                f"{self.api}/kb/search",
                headers=self.headers,
                json={"query": query, "top_k": 5},
                timeout=30,
            )
            if r.status_code != 200:
                fail(f"搜尋失敗: HTTP {r.status_code}")
                self.failed += 1
                continue

            data = r.json()
            results = data.get("results", [])
            total = data.get("total_results", 0)

            if expect:
                # 預期有結果
                top_score = results[0]["score"] if results else 0
                self._assert(
                    total > 0,
                    f"[相關] '{query}' → {total} 結果, top={top_score:.4f}",
                    f"[相關] '{query}' → 無結果（預期應有）",
                )
            else:
                # 不相關查詢 — 結果應分數低或數量少
                if results:
                    top_score = results[0]["score"]
                    info(f"[無關] '{query}' → {total} 結果, top={top_score:.4f}")
                else:
                    info(f"[無關] '{query}' → 0 結果")

    # ── 6. 文件列表 & 狀態統計 ───────────────────

    def test_document_list(self) -> None:
        section("6. 文件列表 API")
        r = requests.get(f"{self.api}/documents/", headers=self.headers, timeout=10)
        self._assert(r.status_code == 200, f"GET /documents/ → HTTP {r.status_code}", f"列表失敗: {r.status_code}")

        docs = r.json()
        if isinstance(docs, list):
            info(f"共 {len(docs)} 個文件")
            status_counts: Dict[str, int] = {}
            for d in docs:
                s = d.get("status", "unknown")
                status_counts[s] = status_counts.get(s, 0) + 1
            for s, c in sorted(status_counts.items()):
                info(f"  {s}: {c}")
        elif isinstance(docs, dict) and "items" in docs:
            info(f"共 {docs.get('total', len(docs['items']))} 個文件")

    # ── 7. 清理 ──────────────────────────────────

    def test_cleanup(self) -> None:
        section("7. 清理測試文件")
        if self.keep:
            info("--keep 模式，跳過清理")
            return

        for doc_id in self.uploaded_ids:
            r = requests.delete(f"{self.api}/documents/{doc_id}", headers=self.headers, timeout=10)
            if r.status_code in (200, 204):
                ok(f"刪除 {doc_id[:8]}...")
            else:
                fail(f"刪除 {doc_id[:8]}... 失敗: {r.status_code}")

    # ── Runner ───────────────────────────────────

    def run(self) -> int:
        print(f"\n{BOLD}{CYAN}╔══════════════════════════════════════════════════════════╗")
        print(f"║          Enclave E2E 全流程測試                         ║")
        print(f"╚══════════════════════════════════════════════════════════╝{RESET}")
        info(f"Target: {self.base_url}")
        info(f"User:   {self.username}")
        info(f"Data:   {TEST_DATA_DIR}")

        if not self.test_login():
            fail("登入失敗，無法繼續測試")
            return 1

        self.test_supported_formats()
        self.test_upload_files()
        self.test_processing()
        self.test_semantic_search()
        self.test_document_list()
        self.test_cleanup()

        # 報告
        section("測試結果摘要")
        total = self.passed + self.failed + self.skipped
        print(f"  {GREEN}通過: {self.passed}{RESET}")
        print(f"  {RED}失敗: {self.failed}{RESET}")
        if self.skipped:
            print(f"  {YELLOW}跳過: {self.skipped}{RESET}")
        print(f"  總計: {total}")

        if self.failed == 0:
            print(f"\n  {GREEN}{BOLD}🎉 ALL TESTS PASSED{RESET}")
        else:
            print(f"\n  {RED}{BOLD}⚠  {self.failed} TEST(S) FAILED{RESET}")

        return 0 if self.failed == 0 else 1


# ── CLI ──────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Enclave E2E Test")
    parser.add_argument("--base-url", default="http://localhost:8001", help="API base URL")
    parser.add_argument("--username", default="admin@example.com", help="Login username")
    parser.add_argument("--password", default="admin123", help="Login password")
    parser.add_argument("--keep", action="store_true", help="Don't cleanup test documents")
    args = parser.parse_args()

    runner = E2ETestRunner(
        base_url=args.base_url,
        username=args.username,
        password=args.password,
        keep=args.keep,
    )
    sys.exit(runner.run())


if __name__ == "__main__":
    main()
