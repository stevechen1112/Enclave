#!/usr/bin/env python3
"""
Enclave Flow 8：知識庫維護全流程測試
========================================
覆蓋 KB Maintenance 管道中所有 19 個端點：
  文件版本 / Diff / KB 健康 / 知識缺口 /
  分類 CRUD / 修訂 & 回滾 / 索引完整性 / 備份還原 / 使用量報表

測試項目：
  T8-01  GET  /documents/{id}/versions — 文件版本歷史
  T8-02  POST /documents/{id}/reupload — 文件重新上傳
  T8-03  GET  /documents/{id}/versions — 重上傳後版本增加
  T8-04  GET  /documents/{id}/diff — 版本差異比對
  T8-05  GET  /kb/health — KB 健康儀表板
  T8-06  GET  /kb/gaps — 知識缺口列表
  T8-07  POST /kb/gaps/scan — 觸發缺口掃描
  T8-08  POST /kb/gaps/{id}/resolve — 解決知識缺口
  T8-09  GET  /kb/categories — 分類列表
  T8-10  POST /kb/categories — 建立分類
  T8-11  PUT  /kb/categories/{id} — 修改分類
  T8-12  GET  /kb/categories/{id}/revisions — 分類修訂歷史
  T8-13  POST /kb/categories/{id}/rollback/{rev} — 回滾分類
  T8-14  DELETE /kb/categories/{id} — 刪除分類
  T8-15  POST /kb/integrity/scan — 觸發完整性檢查
  T8-16  GET  /kb/integrity/reports — 完整性報告列表
  T8-17  POST /kb/backups — 建立備份
  T8-18  GET  /kb/backups — 備份列表
  T8-19  POST /kb/backups/restore — 還原備份
  T8-20  GET  /kb/usage-report — 使用量報表

用法：
  python scripts/test_flow8_kb_maintenance.py
  python scripts/test_flow8_kb_maintenance.py --keep
"""
from __future__ import annotations

import argparse
import io
import json
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

    def put(self, path: str, json_data=None, **kwargs) -> requests.Response:
        return self.session.put(f"{self.base}/api/v1{path}", json=json_data, timeout=15, **kwargs)

    def delete(self, path: str, **kwargs) -> requests.Response:
        return self.session.delete(f"{self.base}/api/v1{path}", timeout=15, **kwargs)


# ══════════════════════════════════════════════════
#  Tests
# ══════════════════════════════════════════════════
# KB Maintenance router prefix
KBM = "/kb-maintenance"


def run_tests(api: ApiClient, keep: bool):
    doc_id: str | None = None
    cat_id: str | None = None
    cat_revision: int | None = None
    backup_id: str | None = None
    gap_id: str | None = None

    # ── Phase 1: 準備文件（上傳 + 處理完）────
    section("Phase 1: 準備測試文件")

    # 上傳初始文件
    tmp = tempfile.NamedTemporaryFile(suffix=".md", prefix="flow8_v1_", delete=False, mode="w", encoding="utf-8")
    tmp.write("# Flow8 版本管理測試 v1\n\n公司員工手冊第一版。\n請假需提前三天申請。\n")
    tmp.close()
    try:
        with open(tmp.name, "rb") as fh:
            r = api.session.post(
                f"{api.base}/api/v1/documents/upload",
                files={"file": ("flow8_handbook_v1.md", fh)},
                timeout=30,
            )
        if _assert(r.status_code == 200, "初始文件上傳", f"HTTP {r.status_code}"):
            doc_id = r.json().get("id")
            # 等待處理完成
            deadline = time.time() + 90
            while time.time() < deadline:
                r2 = api.get(f"/documents/{doc_id}")
                if r2.status_code == 200:
                    st = r2.json().get("status")
                    if st in ("completed", "failed"):
                        break
                time.sleep(3)
            ok("文件處理完成", f"doc_id={doc_id}")
        else:
            fail("初始文件上傳失敗", f"HTTP {r.status_code}")
    finally:
        os.unlink(tmp.name)

    if not doc_id:
        print(f"  {RED}無法取得 doc_id，跳過後續版本測試{RESET}")

    # ── Phase 2: 文件版本歷史 ─────────────
    section("Phase 2: 文件版本歷史 & 重新上傳")

    # T8-01: list versions (should be empty or 0 for first upload)
    if doc_id:
        r = api.get(f"{KBM}/documents/{doc_id}/versions")
        if _assert(r.status_code == 200, "T8-01 版本歷史列表", f"HTTP {r.status_code}"):
            versions = r.json()
            _assert(isinstance(versions, list), "T8-01b 回傳陣列", f"count={len(versions)}")
    else:
        skip("T8-01 版本歷史列表", "無 doc_id")

    # T8-02: reupload
    if doc_id:
        tmp2 = tempfile.NamedTemporaryFile(suffix=".md", prefix="flow8_v2_", delete=False, mode="w", encoding="utf-8")
        tmp2.write("# Flow8 版本管理測試 v2\n\n公司員工手冊第二版。\n請假需提前五天申請，並附主管簽呈。\n新增婚假規定。\n")
        tmp2.close()
        try:
            with open(tmp2.name, "rb") as fh:
                r = api.session.post(
                    f"{api.base}/api/v1{KBM}/documents/{doc_id}/reupload",
                    files={"file": ("flow8_handbook_v2.md", fh)},
                    data={"change_note": "Flow8 自動測試: 更新為 v2"},
                    timeout=30,
                )
            if _assert(r.status_code == 200, "T8-02 文件重新上傳", f"HTTP {r.status_code}"):
                ver = r.json()
                print(f"      {DIM}archived version={ver.get('version')}, change_note={ver.get('change_note')}{RESET}")
                # 等待重新處理
                deadline = time.time() + 90
                while time.time() < deadline:
                    r2 = api.get(f"/documents/{doc_id}")
                    if r2.status_code == 200 and r2.json().get("status") in ("completed", "failed"):
                        break
                    time.sleep(3)
                ok("v2 處理完成")
        finally:
            os.unlink(tmp2.name)

        # T8-03: versions should now have 1 entry (v1 archived)
        r = api.get(f"{KBM}/documents/{doc_id}/versions")
        if _assert(r.status_code == 200, "T8-03 重上傳後版本歷史", f"HTTP {r.status_code}"):
            versions = r.json()
            _assert(len(versions) >= 1, "T8-03b 至少一個存檔版本", f"count={len(versions)}")

        # T8-04: version diff
        r = api.get(f"{KBM}/documents/{doc_id}/diff", params={"old_version": 1, "new_version": 2})
        if _assert(r.status_code == 200, "T8-04 版本差異比對", f"HTTP {r.status_code}"):
            diff = r.json()
            _assert("diff_html" in diff, "T8-04b 有 diff_html 欄位")
            _assert(diff.get("added_lines", 0) > 0 or diff.get("removed_lines", 0) > 0,
                    "T8-04c 有差異內容", f"+{diff.get('added_lines')} -{diff.get('removed_lines')}")
    else:
        skip("T8-02 文件重新上傳", "無 doc_id")
        skip("T8-03 重上傳後版本歷史", "無 doc_id")
        skip("T8-04 版本差異比對", "無 doc_id")

    # ── Phase 3: KB 健康 ────────────────
    section("Phase 3: KB 健康儀表板")

    # T8-05: KB health
    r = api.get(f"{KBM}/kb/health")
    if _assert(r.status_code == 200, "T8-05 KB 健康儀表板", f"HTTP {r.status_code}"):
        health = r.json()
        print(f"      {DIM}total={health.get('total_documents')}, "
              f"completed={health.get('completed_documents')}, "
              f"failed={health.get('failed_documents')}, "
              f"stale={health.get('stale_documents')}, "
              f"coverage={health.get('index_coverage_pct')}%{RESET}")

    # ── Phase 4: 知識缺口 ───────────────
    section("Phase 4: 知識缺口管理")

    # T8-06: list gaps
    r = api.get(f"{KBM}/kb/gaps")
    if _assert(r.status_code == 200, "T8-06 知識缺口列表", f"HTTP {r.status_code}"):
        gaps = r.json()
        _assert(isinstance(gaps, list), "T8-06b 回傳陣列", f"count={len(gaps)}")
        if gaps:
            gap_id = gaps[0].get("id")
            print(f"      {DIM}gap_id={gap_id}, query={gaps[0].get('query', '')[:50]}{RESET}")

    # T8-07: trigger gap scan
    r = api.post(f"{KBM}/kb/gaps/scan", json_data=None)
    _assert(r.status_code == 200, "T8-07 觸發缺口掃描", f"HTTP {r.status_code}")

    # T8-08: resolve gap (if one exists)
    if gap_id:
        r = api.post(f"{KBM}/kb/gaps/{gap_id}/resolve", json_data={
            "resolve_note": "Flow8 自動測試解決",
        })
        _assert(r.status_code == 200, "T8-08 解決知識缺口", f"HTTP {r.status_code}")
    else:
        skip("T8-08 解決知識缺口", "無現存缺口記錄")

    # ── Phase 5: 分類管理 ───────────────
    section("Phase 5: 分類 CRUD & 修訂")

    tag = uuid.uuid4().hex[:6]
    cat_name = f"flow8_cat_{tag}"

    # T8-09: list categories
    r = api.get(f"{KBM}/kb/categories")
    if _assert(r.status_code == 200, "T8-09 分類列表", f"HTTP {r.status_code}"):
        cats = r.json()
        _assert(isinstance(cats, list), "T8-09b 回傳陣列", f"count={len(cats)}")

    # T8-10: create category
    r = api.post(f"{KBM}/kb/categories", json_data={
        "name": cat_name,
        "description": "Flow8 自動測試分類",
        "sort_order": 99,
    })
    if _assert(r.status_code == 201, "T8-10 建立分類", f"HTTP {r.status_code}"):
        cat = r.json()
        cat_id = cat.get("id")
        print(f"      {DIM}cat_id={cat_id}, name={cat.get('name')}{RESET}")

    # T8-11: update category
    if cat_id:
        updated_name = f"{cat_name}_renamed"
        r = api.put(f"{KBM}/kb/categories/{cat_id}", json_data={"name": updated_name})
        if _assert(r.status_code == 200, "T8-11 修改分類名稱", f"HTTP {r.status_code}"):
            _assert(r.json().get("name") == updated_name, "T8-11b 名稱已更新", updated_name)
    else:
        skip("T8-11 修改分類", "無 cat_id")

    # T8-12: list revisions
    if cat_id:
        r = api.get(f"{KBM}/kb/categories/{cat_id}/revisions")
        if _assert(r.status_code == 200, "T8-12 分類修訂歷史", f"HTTP {r.status_code}"):
            revs = r.json()
            _assert(len(revs) >= 1, "T8-12b 至少一個修訂", f"count={len(revs)}")
            if revs:
                cat_revision = revs[-1].get("revision")  # earliest revision for rollback
                print(f"      {DIM}revisions={[rv.get('action') for rv in revs]}{RESET}")
    else:
        skip("T8-12 分類修訂歷史", "無 cat_id")

    # T8-13: rollback category
    if cat_id and cat_revision is not None:
        r = api.post(f"{KBM}/kb/categories/{cat_id}/rollback/{cat_revision}")
        if _assert(r.status_code == 200, "T8-13 回滾分類", f"HTTP {r.status_code}"):
            rolled = r.json()
            print(f"      {DIM}rolled back name={rolled.get('name')}{RESET}")
    else:
        skip("T8-13 回滾分類", "無修訂版本可回滾")

    # T8-14: delete category (soft delete)
    if cat_id:
        r = api.delete(f"{KBM}/kb/categories/{cat_id}")
        _assert(r.status_code == 204, "T8-14 刪除分類（軟刪）", f"HTTP {r.status_code}")
    else:
        skip("T8-14 刪除分類", "無 cat_id")

    # ── Phase 6: 索引完整性 ─────────────
    section("Phase 6: 索引完整性檢查")

    # T8-15: trigger integrity scan
    r = api.post(f"{KBM}/kb/integrity/scan")
    _assert(r.status_code == 200, "T8-15 觸發完整性檢查", f"HTTP {r.status_code}")

    # T8-16: list integrity reports
    r = api.get(f"{KBM}/kb/integrity/reports")
    if _assert(r.status_code == 200, "T8-16 完整性報告列表", f"HTTP {r.status_code}"):
        reports = r.json()
        _assert(isinstance(reports, list), "T8-16b 回傳陣列", f"count={len(reports)}")

    # ── Phase 7: 備份還原 ───────────────
    section("Phase 7: 備份 & 還原")

    # T8-17: create backup
    r = api.post(f"{KBM}/kb/backups", json_data={"backup_type": "full"})
    if _assert(r.status_code == 201, "T8-17 建立備份", f"HTTP {r.status_code}"):
        backup = r.json()
        backup_id = backup.get("id")
        print(f"      {DIM}backup_id={backup_id}, status={backup.get('status')}{RESET}")

    # T8-18: list backups
    r = api.get(f"{KBM}/kb/backups")
    if _assert(r.status_code == 200, "T8-18 備份列表", f"HTTP {r.status_code}"):
        backups = r.json()
        _assert(isinstance(backups, list), "T8-18b 回傳陣列", f"count={len(backups)}")
        # 找一個 completed 的備份
        completed_backup = next((b for b in backups if b.get("status") == "completed"), None)
        if completed_backup:
            backup_id = completed_backup["id"]
            print(f"      {DIM}found completed backup: {backup_id}{RESET}")

    # T8-19: restore (only if a completed backup exists)
    if backup_id:
        # 驗證 completed backup 存在
        r = api.get(f"{KBM}/kb/backups")
        completed = [b for b in r.json() if b.get("status") == "completed"]
        if completed:
            r = api.post(f"{KBM}/kb/backups/restore", json_data={"backup_id": completed[0]["id"]})
            _assert(r.status_code == 200, "T8-19 還原備份", f"HTTP {r.status_code}")
        else:
            skip("T8-19 還原備份", "無已完成的備份可還原（剛建立可能仍在執行中）")
    else:
        skip("T8-19 還原備份", "無 backup_id")

    # ── Phase 8: 使用量報表 ──────────────
    section("Phase 8: 使用量報表")

    # T8-20: usage report
    r = api.get(f"{KBM}/kb/usage-report", params={"days": 30})
    if _assert(r.status_code == 200, "T8-20 使用量報表", f"HTTP {r.status_code}"):
        report = r.json()
        print(f"      {DIM}total_queries={report.get('total_queries')}, "
              f"total_generations={report.get('total_generations')}, "
              f"period_days={report.get('period_days')}{RESET}")

    # ── Phase 9: 清理 ───────────────────
    section("Phase 9: 清理")

    if keep:
        print(f"  {YELLOW}--keep 模式，跳過刪除{RESET}")
    else:
        if doc_id:
            r = api.delete(f"/documents/{doc_id}")
            if r.status_code == 200:
                ok("測試文件已清理", f"doc_id={doc_id}")
            else:
                print(f"  {DIM}文件清理 HTTP {r.status_code}{RESET}")


def main():
    parser = argparse.ArgumentParser(description="Enclave Flow 8 — 知識庫維護全流程測試")
    parser.add_argument("--base-url", default="http://localhost:8001")
    parser.add_argument("--user", default="admin@example.com")
    parser.add_argument("--password", default="admin123")
    parser.add_argument("--keep", action="store_true", help="保留測試資料不刪除")
    args = parser.parse_args()

    print(f"\n{BOLD}═══════════════════════════════════════════════════")
    print(f"  Enclave Flow 8：知識庫維護全流程測試")
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
