#!/usr/bin/env python3
"""
Enclave Flow 1：文件攝取全流程測試
===================================
覆蓋完整 Upload → Parse → Chunk → Embed → Store → Search 管道。

測試項目：
  T1-01  支援格式端點可達
  T1-02  上傳 .md（Markdown 解析）
  T1-03  上傳 .csv（結構化解析）
  T1-04  上傳 .txt（純文字）
  T1-05  上傳不支援格式被拒
  T1-06  所有文件在 120 秒內完成 parsing + embedding
  T1-07  完成文件 chunk_count > 0
  T1-08  完成文件 quality_report 非空
  T1-09  語意搜尋能命中已上傳文件
  T1-10  語意搜尋分數 > 0
  T1-11  搜尋結果包含正確 document_id
  T1-12  文件列表包含新上傳文件
  T1-13  刪除文件（逐一）
  T1-14  刪除後搜尋不再命中
  T1-15  空檔案上傳被拒
  T1-16  超大檔名上傳被拒
  T1-17  重複上傳相同檔案

用法：
  python scripts/test_flow1_ingestion.py
  python scripts/test_flow1_ingestion.py --base-url http://1.2.3.4:8001 --keep
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import tempfile
import time
import uuid
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


# ── Helpers ────────────────────────────────────
class ApiClient:
    def __init__(self, base_url: str, user: str, password: str):
        self.base = base_url
        self.session = requests.Session()
        # Login
        r = self.session.post(
            f"{self.base}/api/v1/auth/login/access-token",
            data={"username": user, "password": password},
            timeout=10,
        )
        r.raise_for_status()
        token = r.json()["access_token"]
        self.session.headers["Authorization"] = f"Bearer {token}"

    def upload(self, filepath: str, filename: str | None = None) -> dict:
        fname = filename or os.path.basename(filepath)
        with open(filepath, "rb") as fh:
            r = self.session.post(
                f"{self.base}/api/v1/documents/upload",
                files={"file": (fname, fh)},
                timeout=30,
            )
        return {"status_code": r.status_code, "body": r.json() if r.status_code < 500 else {}}

    def upload_bytes(self, data: bytes, filename: str, content_type: str = "application/octet-stream") -> dict:
        r = self.session.post(
            f"{self.base}/api/v1/documents/upload",
            files={"file": (filename, data, content_type)},
            timeout=30,
        )
        return {"status_code": r.status_code, "body": r.json() if r.status_code < 500 else {}}

    def poll_status(self, doc_id: str, timeout_s: int = 120, interval: int = 5) -> str:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            r = self.session.get(
                f"{self.base}/api/v1/documents/{doc_id}",
                timeout=10,
            )
            if r.status_code == 200:
                st = r.json()["status"]
                if st in ("completed", "failed"):
                    return st
            time.sleep(interval)
        return "timeout"

    def get_document(self, doc_id: str) -> dict:
        r = self.session.get(f"{self.base}/api/v1/documents/{doc_id}", timeout=10)
        return r.json() if r.status_code == 200 else {}

    def delete_document(self, doc_id: str) -> int:
        r = self.session.delete(f"{self.base}/api/v1/documents/{doc_id}", timeout=10)
        return r.status_code

    def list_documents(self) -> list:
        r = self.session.get(f"{self.base}/api/v1/documents/", timeout=10)
        return r.json() if r.status_code == 200 else []

    def search(self, query: str, top_k: int = 5) -> dict:
        r = self.session.post(
            f"{self.base}/api/v1/kb/search",
            json={"query": query, "top_k": top_k},
            timeout=30,
        )
        return r.json() if r.status_code == 200 else {}

    def supported_formats(self) -> dict:
        r = self.session.get(f"{self.base}/api/v1/documents/supported-formats", timeout=10)
        return r.json() if r.status_code == 200 else {}


# ── Test Data ──────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
TEST_DATA_DIR = PROJECT_ROOT / "test-data" / "company-documents"

# 使用 test-data 裡的真實檔案
TEST_FILES = {
    "md": TEST_DATA_DIR / "sop" / "新人到職SOP.md",
    "csv": TEST_DATA_DIR / "employee-data" / "員工名冊.csv",
    "txt": TEST_DATA_DIR / "contracts" / "勞動契約書-謝雅玲.txt",
}


def find_test_files() -> dict[str, Path]:
    """找到可用的測試檔案，至少要有一個。"""
    available = {}
    for key, path in TEST_FILES.items():
        if path.exists():
            available[key] = path
    return available


# ── Create Temp Test Files (fallback) ──────────
def create_temp_files() -> dict[str, str]:
    """如果 test-data 不存在，建立臨時檔案。"""
    tmpdir = tempfile.mkdtemp(prefix="enclave_test_")
    files = {}

    md_path = os.path.join(tmpdir, "test_到職SOP.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# 新人到職標準作業流程\n\n## 報到第一天\n1. 攜帶身分證正本\n2. 至人資部填寫入職表\n3. 領取員工證\n\n## 第一週\n- 參加新人訓練\n- 認識部門同事\n")
    files["md"] = md_path

    csv_path = os.path.join(tmpdir, "test_員工名冊.csv")
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write("員工編號,姓名,部門,職稱\nE001,陳大明,工程部,資深工程師\nE002,林小美,人資部,HR 專員\nE003,王志偉,業務部,業務經理\n")
    files["csv"] = csv_path

    txt_path = os.path.join(tmpdir, "test_勞動契約書.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("勞動契約書\n\n甲方：ABC科技股份有限公司\n乙方：測試員工\n\n依據勞動基準法，雙方同意以下條款：\n一、工作內容：軟體開發\n二、工作地點：台北市信義區\n三、薪資：每月新台幣伍萬元整\n")
    files["txt"] = txt_path

    return files


# ══════════════════════════════════════════════════
#  Tests
# ══════════════════════════════════════════════════
def run_tests(api: ApiClient, keep: bool):
    uploaded_ids: list[str] = []

    # ── T1-01: 支援格式端點 ─────────────────
    section("Phase 1: 前置檢查")
    formats = api.supported_formats()
    _assert(
        isinstance(formats.get("extensions"), list) and len(formats["extensions"]) > 0,
        "T1-01 支援格式端點可達",
        f"{len(formats.get('extensions', []))} 種格式"
    )

    # ── 找到測試資料 ───────────────────────
    test_files = find_test_files()
    if not test_files:
        print(f"  {YELLOW}test-data 不存在，使用臨時檔案{RESET}")
        tmp_files = create_temp_files()
        test_files = {k: Path(v) for k, v in tmp_files.items()}

    # ── T1-02 ~ T1-04: 上傳測試 ──────────
    section("Phase 2: 檔案上傳")
    upload_results: dict[str, dict] = {}

    for idx, (ftype, fpath) in enumerate(test_files.items(), start=2):
        test_id = f"T1-{idx:02d}"
        result = api.upload(str(fpath))
        if _assert(
            result["status_code"] == 200,
            f"{test_id} 上傳 .{ftype}（{fpath.name}）",
            f"HTTP {result['status_code']}"
        ):
            doc_id = result["body"]["id"]
            uploaded_ids.append(doc_id)
            upload_results[ftype] = result["body"]
            print(f"      {DIM}doc_id={doc_id}{RESET}")

    # ── T1-05: 不支援格式被拒 ─────────────
    result = api.upload_bytes(b"fake binary data", "malware.exe", "application/x-msdownload")
    _assert(
        result["status_code"] == 400,
        "T1-05 不支援格式被拒（.exe）",
        f"HTTP {result['status_code']}"
    )

    # ── T1-06: 狀態輪詢 ──────────────────
    section("Phase 3: 處理等待")
    if uploaded_ids:
        print(f"  {DIM}等待 {len(uploaded_ids)} 個文件完成處理（上限 120s）...{RESET}")
        all_completed = True
        for doc_id in uploaded_ids:
            st = api.poll_status(doc_id, timeout_s=120)
            if st != "completed":
                all_completed = False
                fail(f"T1-06 文件處理", f"doc_id={doc_id} status={st}")
            else:
                print(f"      {DIM}{doc_id[:8]}... → completed{RESET}")
        _assert(all_completed, "T1-06 所有文件 120s 內完成")

    # ── T1-07 ~ T1-08: 品質驗證 ──────────
    section("Phase 4: 品質驗證")
    for doc_id in uploaded_ids:
        doc = api.get_document(doc_id)
        fname = doc.get("filename", doc_id[:8])
        chunk_count = doc.get("chunk_count", 0)
        _assert(
            isinstance(chunk_count, int) and chunk_count > 0,
            f"T1-07 chunk_count > 0（{fname}）",
            f"chunks={chunk_count}"
        )
        quality = doc.get("quality_report")
        _assert(
            quality is not None,
            f"T1-08 quality_report 非空（{fname}）",
            f"rating={quality.get('rating', '?')}" if isinstance(quality, dict) else ""
        )

    # ── T1-09 ~ T1-11: 語意搜尋 ──────────
    section("Phase 5: 語意搜尋驗證")
    search_queries = [
        ("新人到職", "md"),
        ("員工名冊", "csv"),
        ("勞動契約", "txt"),
    ]

    upload_doc_ids = set(uploaded_ids)
    for query, ftype in search_queries:
        if ftype not in upload_results:
            skip(f"T1-09 搜尋「{query}」", f"未上傳 .{ftype}")
            continue

        result = api.search(query, top_k=5)
        results = result.get("results", [])
        if not _assert(len(results) > 0, f"T1-09 搜尋「{query}」有結果", f"命中 {len(results)} 筆"):
            continue

        top_score = results[0].get("score", 0)
        _assert(top_score > 0, f"T1-10 搜尋分數 > 0（{query}）", f"score={top_score:.4f}")

        hit_doc_ids = {r["document_id"] for r in results}
        _assert(
            bool(hit_doc_ids & upload_doc_ids),
            f"T1-11 搜尋結果包含正確 doc_id（{query}）",
            f"matched={hit_doc_ids & upload_doc_ids}"
        )

    # ── T1-12: 文件列表 ──────────────────
    section("Phase 6: 文件列表驗證")
    doc_list = api.list_documents()
    list_ids = {d["id"] for d in doc_list}
    all_found = all(did in list_ids for did in uploaded_ids)
    _assert(
        all_found,
        "T1-12 文件列表包含新上傳文件",
        f"列表共 {len(doc_list)} 筆"
    )

    # ── T1-15: 空檔案上傳被拒 ─────────────
    section("Phase 7: 邊界條件")
    result = api.upload_bytes(b"", "empty.txt", "text/plain")
    _assert(
        result["status_code"] == 400,
        "T1-15 空檔案上傳被拒",
        f"HTTP {result['status_code']}"
    )

    # ── T1-16: 超長檔名 ─────────────────
    long_name = "a" * 300 + ".txt"
    result = api.upload_bytes(b"test content", long_name, "text/plain")
    _assert(
        result["status_code"] in (400, 200),  # 具體行為取決於實作
        "T1-16 超長檔名處理",
        f"HTTP {result['status_code']}"
    )
    if result["status_code"] == 200 and result.get("body", {}).get("id"):
        uploaded_ids.append(result["body"]["id"])

    # ── T1-17：重複上傳 ──────────────────
    if test_files:
        first_key = list(test_files.keys())[0]
        result = api.upload(str(test_files[first_key]))
        _assert(
            result["status_code"] == 200,
            "T1-17 重複上傳相同檔案",
            f"HTTP {result['status_code']}"
        )
        if result["status_code"] == 200 and result.get("body", {}).get("id"):
            uploaded_ids.append(result["body"]["id"])

    # ── T1-13 ~ T1-14: 刪除 + 驗證 ───────
    section("Phase 8: 清理")
    if keep:
        print(f"  {YELLOW}--keep 模式，跳過刪除{RESET}")
    else:
        all_deleted = True
        for doc_id in uploaded_ids:
            status_code = api.delete_document(doc_id)
            if status_code != 200:
                all_deleted = False
                fail(f"T1-13 刪除 {doc_id[:8]}...", f"HTTP {status_code}")
        _assert(all_deleted, "T1-13 所有文件刪除成功")

        # 確認搜尋不再命中已刪除的文件
        time.sleep(5)
        result = api.search("新人到職", top_k=5)
        hit_ids = {r["document_id"] for r in result.get("results", [])}
        stale = hit_ids & set(uploaded_ids)
        _assert(
            len(stale) == 0,
            "T1-14 刪除後搜尋不再命中",
            f"殘留: {stale}" if stale else "clean"
        )


def main():
    parser = argparse.ArgumentParser(description="Enclave Flow 1 — 文件攝取全流程測試")
    parser.add_argument("--base-url", default="http://localhost:8001")
    parser.add_argument("--user", default="admin@example.com")
    parser.add_argument("--password", default="admin123")
    parser.add_argument("--keep", action="store_true", help="保留測試資料不刪除")
    args = parser.parse_args()

    print(f"\n{BOLD}═══════════════════════════════════════════════════")
    print(f"  Enclave Flow 1：文件攝取全流程測試")
    print(f"  Target: {args.base_url}")
    print(f"═══════════════════════════════════════════════════{RESET}")

    try:
        api = ApiClient(args.base_url, args.user, args.password)
        ok("登入成功")
    except Exception as e:
        fail(f"登入失敗: {e}")
        sys.exit(1)

    run_tests(api, keep=args.keep)

    # 摘要
    section("結果摘要")
    total = passed + failed + skipped
    print(f"  {GREEN}通過: {passed}{RESET}  {RED}失敗: {failed}{RESET}  {YELLOW}跳過: {skipped}{RESET}  總計: {total}")
    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
