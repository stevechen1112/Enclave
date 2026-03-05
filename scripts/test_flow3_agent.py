#!/usr/bin/env python3
"""
Enclave Flow 3：Agent 自動索引全流程測試
==========================================
覆蓋 Folder Watch → Scan → Classify → Review → Approve/Reject → Ingest 管道。
這是系統中覆蓋率最低的區域（原本 0%）。

測試項目：
  T3-01  Agent 狀態端點可達
  T3-02  瀏覽伺服器目錄（browse）
  T3-03  新增監控資料夾
  T3-04  資料夾列表包含新增項目
  T3-05  切換資料夾 active/inactive
  T3-06  觸發手動掃描
  T3-07  掃描預覽（scan-preview with Ollama）
  T3-08  審核佇列有待審項目
  T3-09  核准單一項目
  T3-10  駁回單一項目
  T3-11  修改並核准項目
  T3-12  批次核准
  T3-13  批次處理狀態摘要
  T3-14  啟動 Agent watcher
  T3-15  停止 Agent watcher
  T3-16  刪除監控資料夾
  T3-17  批次重索引觸發

用法：
  python scripts/test_flow3_agent.py
  python scripts/test_flow3_agent.py --keep
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
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

    def patch(self, path: str, json_data=None, **kwargs) -> requests.Response:
        return self.session.patch(f"{self.base}/api/v1{path}", json=json_data, timeout=15, **kwargs)


# ── Test Data ──────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
# Docker 容器將專案掛載在 /code，Agent API 在 server 端運作
# 必須使用 Docker 內部路徑，而非本機 Windows 路徑
DOCKER_TEST_FOLDER = "/code/test-data/company-documents/sop"
LOCAL_TEST_WATCH_DIR = PROJECT_ROOT / "test-data" / "company-documents" / "sop"


def get_test_folder_path() -> str:
    """取得可用的測試資料夾路徑（Docker 內部路徑）。"""
    # Agent API 跑在 Docker 內，資料夾路徑必須是容器可見的路徑
    if LOCAL_TEST_WATCH_DIR.exists():
        return DOCKER_TEST_FOLDER

    # Fallback: 在專案目錄內建立臨時目錄（Docker 掛載可見）
    fallback_dir = PROJECT_ROOT / "test-data" / "_agent_test_tmp"
    fallback_dir.mkdir(parents=True, exist_ok=True)
    for i in range(3):
        fpath = fallback_dir / f"test_doc_{i}.md"
        if not fpath.exists():
            fpath.write_text(
                f"# 測試文件 {i}\n\n這是 Agent 測試用的文件內容。\n" * 5,
                encoding="utf-8",
            )
    return "/code/test-data/_agent_test_tmp"


# ══════════════════════════════════════════════════
#  Tests
# ══════════════════════════════════════════════════
def run_tests(api: ApiClient, keep: bool):
    created_folder_id = None
    review_item_ids: list[str] = []

    # ── Phase 1: 狀態檢查 ────────────────
    section("Phase 1: Agent 狀態")

    # T3-01: Agent status
    r = api.get("/agent/status")
    if _assert(r.status_code == 200, "T3-01 Agent 狀態端點", f"HTTP {r.status_code}"):
        status = r.json()
        watcher = status.get("watcher_running", False)
        folders = status.get("active_folders", 0)
        pending = status.get("pending_review_count", 0)
        print(f"      {DIM}watcher={watcher}, folders={folders}, pending={pending}{RESET}")

    # T3-02: Browse
    r = api.get("/agent/browse", params={"path": ""})
    if _assert(r.status_code == 200, "T3-02 瀏覽伺服器目錄", f"HTTP {r.status_code}"):
        browse = r.json()
        entries = browse.get("dirs", [])
        print(f"      {DIM}root has {len(entries)} entries{RESET}")

    # ── Phase 2: 資料夾管理 ──────────────
    section("Phase 2: 監控資料夾管理")

    test_folder_path = get_test_folder_path()
    print(f"  {DIM}測試資料夾: {test_folder_path}{RESET}")

    # T3-03: 新增資料夾
    r = api.post("/agent/folders", json_data={
        "folder_path": test_folder_path,
        "display_name": "Flow3 Test Folder",
        "recursive": True,
        "max_depth": 5,
        "default_category": "測試"
    })
    if _assert(r.status_code in (200, 201), "T3-03 新增監控資料夾", f"HTTP {r.status_code}"):
        folder_data = r.json()
        created_folder_id = folder_data.get("id")
        print(f"      {DIM}folder_id={created_folder_id}{RESET}")
    elif r.status_code == 409:
        # 資料夾已存在 — 從列表取得 ID
        ok("T3-03 監控資料夾已存在（409）")
        r2 = api.get("/agent/folders")
        if r2.status_code == 200:
            for f in r2.json():
                if f.get("folder_path") == test_folder_path:
                    created_folder_id = f.get("id")
                    break

    # T3-04: 資料夾列表
    r = api.get("/agent/folders")
    if _assert(r.status_code == 200, "T3-04 資料夾列表", f"HTTP {r.status_code}"):
        folders = r.json()
        folder_ids = [str(f.get("id", "")) for f in folders]
        if created_folder_id:
            _assert(
                str(created_folder_id) in folder_ids,
                "T3-04b 列表包含新增資料夾",
                f"total={len(folders)}"
            )
        else:
            print(f"      {DIM}共 {len(folders)} 個監控資料夾{RESET}")

    # T3-05: Toggle
    if created_folder_id:
        r = api.patch(f"/agent/folders/{created_folder_id}/toggle")
        _assert(
            r.status_code == 200,
            "T3-05 切換資料夾 active/inactive",
            f"HTTP {r.status_code}"
        )
        # Toggle back
        api.patch(f"/agent/folders/{created_folder_id}/toggle")
    else:
        skip("T3-05 切換資料夾", "無 folder_id")

    # ── Phase 3: 掃描 ───────────────────
    section("Phase 3: 掃描 & 分類")

    # T3-06: 手動掃描
    r = api.post("/agent/scan")
    _assert(
        r.status_code in (200, 503),
        "T3-06 觸發手動掃描",
        f"HTTP {r.status_code}"
    )

    # 等待掃描完成
    print(f"  {DIM}等待掃描 + 分類處理（15s）...{RESET}")
    time.sleep(15)

    # T3-07: scan-preview
    r = api.post("/agent/scan-preview", json_data={
        "subfolders": [
            {
                "path": "sop",
                "name": "SOP",
                "files": ["新人到職SOP.md"],
                "content_samples": ["這是新人到職的標準作業流程，包含報到、訓練、領取設備等步驟。"]
            }
        ]
    })
    if _assert(r.status_code == 200, "T3-07 掃描預覽（Ollama 分類）", f"HTTP {r.status_code}"):
        preview = r.json()
        subfolders = preview.get("subfolders", [])
        if subfolders:
            print(f"      {DIM}summary: {subfolders[0].get('summary', '?')[:80]}{RESET}")

    # ── Phase 4: 審核佇列 ────────────────
    section("Phase 4: 審核佇列")

    # T3-08: 取得審核項目
    r = api.get("/agent/review", params={"limit": 50})
    if _assert(r.status_code == 200, "T3-08 審核佇列端點", f"HTTP {r.status_code}"):
        review_data = r.json()
        items = review_data.get("items", [])
        total = review_data.get("total", 0)
        print(f"      {DIM}total={total}, returned={len(items)}{RESET}")

        # 收集 item IDs
        review_item_ids = [item["id"] for item in items if item.get("status") == "pending"]

        if items:
            first = items[0]
            print(f"      {DIM}first: file={first.get('file_name')}, "
                  f"category={first.get('suggested_category')}, "
                  f"confidence={first.get('confidence_score')}{RESET}")

    # T3-09: 核准單一項目
    if len(review_item_ids) > 0:
        item_id = review_item_ids[0]
        r = api.post(f"/agent/review/{item_id}/approve")
        _assert(
            r.status_code == 200,
            "T3-09 核准單一項目",
            f"item_id={item_id[:8]}..."
        )
    else:
        skip("T3-09 核准單一項目", "無待審項目")

    # T3-10: 駁回單一項目
    if len(review_item_ids) > 1:
        item_id = review_item_ids[1]
        r = api.post(f"/agent/review/{item_id}/reject", json_data={"reason": "自動測試駁回"})
        _assert(
            r.status_code == 200,
            "T3-10 駁回單一項目",
            f"item_id={item_id[:8]}..."
        )
    else:
        skip("T3-10 駁回單一項目", "不足 2 個待審項目")

    # T3-11: 修改並核准
    if len(review_item_ids) > 2:
        item_id = review_item_ids[2]
        r = api.post(f"/agent/review/{item_id}/modify", json_data={
            "category": "modified_by_test",
            "tags": {"source": "auto-test"},
            "note": "Flow3 自動測試修改"
        })
        _assert(
            r.status_code == 200,
            "T3-11 修改並核准",
            f"item_id={item_id[:8]}..."
        )
    else:
        skip("T3-11 修改並核准", "不足 3 個待審項目")

    # T3-12: 批次核准
    remaining_ids = review_item_ids[3:6]  # 取最多 3 個
    if remaining_ids:
        r = api.post("/agent/review/batch-approve", json_data={"item_ids": remaining_ids})
        _assert(
            r.status_code == 200,
            "T3-12 批次核准",
            f"requested={len(remaining_ids)}, approved={r.json().get('approved_count', '?')}"
            if r.status_code == 200 else f"HTTP {r.status_code}"
        )
    else:
        skip("T3-12 批次核准", "不足批次處理的項目")

    # ── Phase 5: 批次管理 ────────────────
    section("Phase 5: 批次管理")

    # T3-13: 批次狀態
    r = api.get("/agent/batches")
    if _assert(r.status_code == 200, "T3-13 批次狀態摘要", f"HTTP {r.status_code}"):
        batch_data = r.json()
        summary = batch_data.get("status_summary", {})
        print(f"      {DIM}{json.dumps(summary, ensure_ascii=False)}{RESET}")

    # T3-17: 批次重索引
    r = api.post("/agent/batches/trigger")
    _assert(
        r.status_code in (200, 503),
        "T3-17 批次重索引觸發",
        f"triggered_at={r.json().get('triggered_at')}" if r.status_code == 200 else f"HTTP {r.status_code}"
    )

    # ── Phase 6: Agent 生命週期 ──────────
    section("Phase 6: Agent Watcher 生命週期")

    # T3-14: 啟動
    r = api.post("/agent/start")
    _assert(
        r.status_code == 200,
        "T3-14 啟動 Agent watcher",
        f"HTTP {r.status_code}"
    )

    time.sleep(2)

    # 確認狀態
    r = api.get("/agent/status")
    if r.status_code == 200:
        status = r.json()
        print(f"      {DIM}啟動後: watcher={status.get('watcher_running')}{RESET}")

    # T3-15: 停止
    r = api.post("/agent/stop")
    _assert(
        r.status_code == 200,
        "T3-15 停止 Agent watcher",
        f"HTTP {r.status_code}"
    )

    # ── Phase 7: 清理 ───────────────────
    section("Phase 7: 清理")
    if keep:
        print(f"  {YELLOW}--keep 模式，跳過刪除{RESET}")
    else:
        if created_folder_id:
            r = api.delete(f"/agent/folders/{created_folder_id}")
            _assert(
                r.status_code in (200, 204),
                "T3-16 刪除監控資料夾",
                f"HTTP {r.status_code}"
            )
        else:
            skip("T3-16 刪除監控資料夾", "無 folder_id")


def main():
    parser = argparse.ArgumentParser(description="Enclave Flow 3 — Agent 自動索引全流程測試")
    parser.add_argument("--base-url", default="http://localhost:8001")
    parser.add_argument("--user", default="admin@example.com")
    parser.add_argument("--password", default="admin123")
    parser.add_argument("--keep", action="store_true", help="保留測試資料不刪除")
    args = parser.parse_args()

    print(f"\n{BOLD}═══════════════════════════════════════════════════")
    print(f"  Enclave Flow 3：Agent 自動索引全流程測試")
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
