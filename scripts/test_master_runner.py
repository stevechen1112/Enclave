#!/usr/bin/env python3
"""
Enclave 全流程測試主控腳本
============================
依序執行所有測試腳本，彙整結果報告。

執行順序：
  1. 基礎設施健康檢查
  2. Flow 1 — 文件攝取
  3. Flow 2 — RAG 對話
  4. Flow 3 — Agent 自動索引
  5. Flow 4 — 內容生成
  6. Flow 5 — 50+ 檔案大量 Agent 處理
  7. Flow 6 — 平台管理 & 權限
  8. Flow 7 — 分析 & 稽核
  9. Flow 8 — 知識庫維護

用法：
  python scripts/test_master_runner.py
  python scripts/test_master_runner.py --base-url http://1.2.3.4:8001
  python scripts/test_master_runner.py --skip infra
  python scripts/test_master_runner.py --only flow1 flow2
  python scripts/test_master_runner.py --keep
"""
from __future__ import annotations

import argparse
import io
import os
import subprocess
import sys
import time
from pathlib import Path

# Windows cp950 workaround: force UTF-8 stdout
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ── UI ─────────────────────────────────────────
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

SCRIPT_DIR = Path(__file__).resolve().parent

# 測試腳本清單
SUITES = {
    "infra": {
        "name": "基礎設施健康檢查",
        "script": SCRIPT_DIR / "test_infra_health.py",
        "emoji": "[INFRA]",
    },
    "flow1": {
        "name": "Flow 1 — 文件攝取",
        "script": SCRIPT_DIR / "test_flow1_ingestion.py",
        "emoji": "[F1]",
    },
    "flow2": {
        "name": "Flow 2 — RAG 對話",
        "script": SCRIPT_DIR / "test_flow2_rag_chat.py",
        "emoji": "[F2]",
    },
    "flow3": {
        "name": "Flow 3 — Agent 自動索引",
        "script": SCRIPT_DIR / "test_flow3_agent.py",
        "emoji": "[F3]",
    },
    "flow4": {
        "name": "Flow 4 — 內容生成",
        "script": SCRIPT_DIR / "test_flow4_generation.py",
        "emoji": "[F4]",
    },
    "flow5": {
        "name": "Flow 5 — 50+ 大量 Agent",
        "script": SCRIPT_DIR / "test_flow5_bulk_agent.py",
        "emoji": "[F5]",
    },
    "flow6": {
        "name": "Flow 6 — 平台管理 & 權限",
        "script": SCRIPT_DIR / "test_flow6_platform_admin.py",
        "emoji": "[F6]",
    },
    "flow7": {
        "name": "Flow 7 — 分析 & 稽核",
        "script": SCRIPT_DIR / "test_flow7_analytics_audit.py",
        "emoji": "[F7]",
    },
    "flow8": {
        "name": "Flow 8 -- 知識庫維護",
        "script": SCRIPT_DIR / "test_flow8_kb_maintenance.py",
        "emoji": "[F8]",
    },
    "recovery": {
        "name": "故障恢復測試",
        "script": SCRIPT_DIR / "test_fault_recovery.py",
        "emoji": "[REC]",
    },
    "stress": {
        "name": "壓力併發測試",
        "script": SCRIPT_DIR / "test_stress_concurrent.py",
        "emoji": "[STR]",
    },
    "alembic": {
        "name": "Alembic 遷移驗證",
        "script": SCRIPT_DIR / "test_alembic_migration.py",
        "emoji": "[ALM]",
    },
    "security": {
        "name": "安全掃描",
        "script": SCRIPT_DIR / "test_security_scan.py",
        "emoji": "[SEC]",
    },
    "monitor": {
        "name": "監控告警驗證",
        "script": SCRIPT_DIR / "test_monitoring.py",
        "emoji": "[MON]",
    },
}


def run_suite(
    key: str,
    suite: dict,
    base_url: str,
    user: str,
    password: str,
    keep: bool,
) -> dict:
    """執行單一測試套件，回傳結果。"""
    script = suite["script"]
    name = suite["name"]

    print(f"\n{BOLD}{CYAN}{'═' * 60}")
    print(f"  {suite['emoji']}  {name}")
    print(f"{'═' * 60}{RESET}")

    if not script.exists():
        print(f"  {RED}✘ 腳本不存在: {script}{RESET}")
        return {"key": key, "name": name, "status": "missing", "exit_code": -1, "duration": 0}

    cmd = [sys.executable, str(script), "--base-url", base_url, "--user", user, "--password", password]
    if keep and key != "infra":
        cmd.append("--keep")

    # Flow 5 (bulk) and Flow 8 (KB maintenance with reupload) need longer timeout
    # Recovery and stress tests also need extra time
    timeout = 1200 if key in ("flow5", "flow8", "recovery", "stress") else 600

    start_time = time.time()
    try:
        result = subprocess.run(
            cmd,
            cwd=str(SCRIPT_DIR.parent),
            timeout=timeout,
        )
        duration = time.time() - start_time
        exit_code = result.returncode
    except subprocess.TimeoutExpired:
        duration = time.time() - start_time
        exit_code = -2
        print(f"\n  {RED}⏰ 超時（{timeout}s）{RESET}")
    except Exception as e:
        duration = time.time() - start_time
        exit_code = -3
        print(f"\n  {RED}✘ 執行異常: {e}{RESET}")

    status = "pass" if exit_code == 0 else "fail" if exit_code > 0 else "error"
    return {"key": key, "name": name, "status": status, "exit_code": exit_code, "duration": duration}


def print_report(results: list[dict]):
    """印出最終彙整報告。"""
    print(f"\n\n{BOLD}{'═' * 60}")
    print(f"       Enclave 全流程測試報告")
    print(f"{'═' * 60}{RESET}\n")

    total_pass = 0
    total_fail = 0
    total_error = 0
    total_time = 0

    for r in results:
        status = r["status"]
        duration = r["duration"]
        total_time += duration

        if status == "pass":
            total_pass += 1
            icon = f"{GREEN}✔ PASS{RESET}"
        elif status == "fail":
            total_fail += 1
            icon = f"{RED}✘ FAIL{RESET}"
        elif status == "missing":
            total_error += 1
            icon = f"{YELLOW}⊘ MISSING{RESET}"
        elif status == "error":
            total_error += 1
            icon = f"{RED}⚠ ERROR{RESET}"
        else:
            total_error += 1
            icon = f"{YELLOW}? {status.upper()}{RESET}"

        print(f"  {icon}  {r['name']:<30s}  {DIM}{duration:.1f}s{RESET}")

    print(f"\n{'─' * 60}")
    print(f"  總耗時: {total_time:.1f}s")
    print(f"  {GREEN}通過: {total_pass}{RESET}  "
          f"{RED}失敗: {total_fail}{RESET}  "
          f"{YELLOW}錯誤: {total_error}{RESET}  "
          f"總計: {len(results)}")

    if total_fail > 0 or total_error > 0:
        print(f"\n  {RED}{BOLD}⚠ 有 {total_fail + total_error} 個測試套件不通過！{RESET}")
    else:
        print(f"\n  {GREEN}{BOLD}✔ 所有測試套件通過！{RESET}")

    print(f"{'═' * 60}\n")


def main():
    parser = argparse.ArgumentParser(description="Enclave 全流程測試主控腳本")
    parser.add_argument("--base-url", default="http://localhost:8001", help="API 基礎 URL")
    parser.add_argument("--user", default="admin@example.com")
    parser.add_argument("--password", default="admin123")
    parser.add_argument("--keep", action="store_true", help="保留所有測試資料不刪除")
    parser.add_argument("--skip", nargs="*", default=[], choices=SUITES.keys(),
                        help="跳過特定套件（如: --skip infra flow3）")
    parser.add_argument("--only", nargs="*", default=[], choices=SUITES.keys(),
                        help="僅執行特定套件（如: --only flow1 flow2）")
    args = parser.parse_args()

    print(f"\n{BOLD}{'═' * 60}")
    print(f"       Enclave 全流程測試主控")
    print(f"       Target: {args.base_url}")
    print(f"{'═' * 60}{RESET}")

    # 決定要跑的套件
    if args.only:
        suite_keys = [k for k in SUITES if k in args.only]
    else:
        suite_keys = [k for k in SUITES if k not in args.skip]

    print(f"\n  {DIM}將執行 {len(suite_keys)} 個套件: {', '.join(suite_keys)}{RESET}")

    results = []
    for key in suite_keys:
        result = run_suite(
            key=key,
            suite=SUITES[key],
            base_url=args.base_url,
            user=args.user,
            password=args.password,
            keep=args.keep,
        )
        results.append(result)

        # 如果 infra 失敗，詢問是否繼續
        if key == "infra" and result["status"] != "pass":
            print(f"\n  {YELLOW}⚠ 基礎設施檢查未通過，後續測試可能不穩定{RESET}")

    print_report(results)

    any_failure = any(r["status"] in ("fail", "error") for r in results)
    sys.exit(1 if any_failure else 0)


if __name__ == "__main__":
    main()
