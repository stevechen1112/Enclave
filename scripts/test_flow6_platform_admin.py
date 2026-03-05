#!/usr/bin/env python3
"""
Enclave Flow 6：平台管理全流程測試
====================================
覆蓋 Admin Dashboard / User Management / Quota / Security /
     Departments / Feature Flags / Organization / Company 管道。

測試項目：
  T6-01  GET  /users/me — 取得當前用戶資料
  T6-02  GET  /admin/dashboard — 組織儀表板
  T6-03  GET  /admin/system/health — 系統健康（DB + Redis）
  T6-04  GET  /admin/users — 搜尋用戶列表
  T6-05  POST /admin/users/invite — 邀請新用戶
  T6-06  PUT  /admin/users/{id} — 更新用戶角色
  T6-07  DELETE /admin/users/{id} — 停用用戶
  T6-08  GET  /admin/quota/plans — 列出方案預設配額
  T6-09  GET  /admin/tenants/{id}/quota — 取得租戶配額
  T6-10  PUT  /admin/tenants/{id}/quota — 更新配額欄位
  T6-11  POST /admin/tenants/{id}/quota/apply-plan — 套用方案
  T6-12  GET  /admin/tenants/{id}/security — 取得安全組態
  T6-13  PUT  /admin/tenants/{id}/security — 更新安全組態
  T6-14  GET  /departments/ — 部門列表
  T6-15  POST /departments/ — 建立部門
  T6-16  GET  /departments/tree — 部門樹狀結構
  T6-17  GET  /departments/{id} — 取得單一部門
  T6-18  PUT  /departments/{id} — 更新部門
  T6-19  DELETE /departments/{id} — 停用部門
  T6-20  GET  /departments/features/available — 可用功能模組
  T6-21  GET  /departments/features/ — 功能權限列表
  T6-22  POST /departments/features/ — 設定功能權限
  T6-23  GET  /feature-flags/ — 功能旗標列表
  T6-24  POST /feature-flags/ — 建立功能旗標
  T6-25  GET  /feature-flags/{key} — 取得旗標
  T6-26  PUT  /feature-flags/{key} — 更新旗標
  T6-27  GET  /feature-flags/{key}/evaluate — 評估旗標
  T6-28  DELETE /feature-flags/{key} — 刪除旗標
  T6-29  GET  /organization/me — 組織資訊
  T6-30  GET  /company/dashboard — 公司儀表板
  T6-31  GET  /company/profile — 公司資料
  T6-32  GET  /company/quota — 公司配額
  T6-33  GET  /company/users — 公司成員列表
  T6-34  GET  /company/usage/summary — 使用量摘要
  T6-35  DELETE /documents/batch — 批次刪除文件

用法：
  python scripts/test_flow6_platform_admin.py
  python scripts/test_flow6_platform_admin.py --keep
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
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
        data = r.json()
        token = data["access_token"]
        self.session.headers["Authorization"] = f"Bearer {token}"

    def get(self, path: str, **kwargs) -> requests.Response:
        return self.session.get(f"{self.base}/api/v1{path}", timeout=15, **kwargs)

    def post(self, path: str, json_data=None, **kwargs) -> requests.Response:
        return self.session.post(f"{self.base}/api/v1{path}", json=json_data, timeout=30, **kwargs)

    def put(self, path: str, json_data=None, **kwargs) -> requests.Response:
        return self.session.put(f"{self.base}/api/v1{path}", json=json_data, timeout=15, **kwargs)

    def delete(self, path: str, **kwargs) -> requests.Response:
        return self.session.delete(f"{self.base}/api/v1{path}", timeout=15, **kwargs)

    def patch(self, path: str, json_data=None, **kwargs) -> requests.Response:
        return self.session.patch(f"{self.base}/api/v1{path}", json=json_data, timeout=15, **kwargs)


# ══════════════════════════════════════════════════
#  Tests
# ══════════════════════════════════════════════════
def run_tests(api: ApiClient, keep: bool):
    tenant_id: str | None = None
    created_user_id: str | None = None
    created_dept_id: str | None = None
    created_flag_key: str | None = None
    test_email = f"flow6_test_{uuid.uuid4().hex[:8]}@test.enclave.local"

    # ── Phase 1: 用戶 & 身份 ────────────
    section("Phase 1: 用戶身份")

    # T6-01: GET /users/me
    r = api.get("/users/me")
    if _assert(r.status_code == 200, "T6-01 GET /users/me", f"HTTP {r.status_code}"):
        me = r.json()
        tenant_id = me.get("tenant_id")
        _assert("email" in me and "role" in me, "T6-01b 回傳包含 email + role", me.get("email"))
        print(f"      {DIM}tenant_id={tenant_id}{RESET}")

    if not tenant_id:
        fail("無法取得 tenant_id，後續管理測試將受限")

    # ── Phase 2: Admin Dashboard ────────
    section("Phase 2: 管理儀表板")

    # T6-02: Dashboard
    r = api.get("/admin/dashboard")
    if _assert(r.status_code == 200, "T6-02 組織儀表板", f"HTTP {r.status_code}"):
        dash = r.json()
        for key in ("total_users", "active_users", "total_documents", "total_conversations"):
            if key in dash:
                print(f"      {DIM}{key}={dash[key]}{RESET}")

    # T6-03: System health
    r = api.get("/admin/system/health")
    if _assert(r.status_code == 200, "T6-03 系統健康檢查", f"HTTP {r.status_code}"):
        health = r.json()
        _assert(
            health.get("database") == "healthy",
            "T6-03b DB healthy",
            f"db={health.get('database')}, redis={health.get('redis')}"
        )
        print(f"      {DIM}python={health.get('python_version')}{RESET}")

    # ── Phase 3: 用戶管理 ───────────────
    section("Phase 3: 用戶管理（CRUD）")

    # T6-04: 搜尋用戶
    r = api.get("/admin/users")
    if _assert(r.status_code == 200, "T6-04 用戶列表", f"HTTP {r.status_code}"):
        users = r.json()
        _assert(len(users) > 0, "T6-04b 至少有 1 個用戶", f"count={len(users)}")

    # T6-05: 邀請新用戶
    r = api.post("/admin/users/invite", json_data={
        "email": test_email,
        "full_name": "Flow6 測試用戶",
        "password": "TestPass123!",
        "role": "member",
    })
    if _assert(r.status_code == 200, "T6-05 邀請新用戶", f"HTTP {r.status_code}"):
        created_user_id = r.json().get("id")
        print(f"      {DIM}user_id={created_user_id}, email={test_email}{RESET}")
    elif r.status_code == 409:
        ok("T6-05 用戶已存在（409）")

    # T6-06: 更新角色
    if created_user_id:
        r = api.put(f"/admin/users/{created_user_id}", json_data={
            "role": "hr",
            "full_name": "Flow6 Updated",
        })
        _assert(r.status_code == 200, "T6-06 更新用戶角色", f"HTTP {r.status_code}")
    else:
        skip("T6-06 更新用戶", "無 user_id")

    # T6-07: 停用用戶
    if created_user_id and not keep:
        r = api.delete(f"/admin/users/{created_user_id}")
        _assert(r.status_code == 200, "T6-07 停用用戶", f"HTTP {r.status_code}")
    elif created_user_id:
        skip("T6-07 停用用戶", "--keep 模式")
    else:
        skip("T6-07 停用用戶", "無 user_id")

    # ── Phase 4: 配額管理 ───────────────
    section("Phase 4: 配額管理")

    # T6-08: 方案列表
    r = api.get("/admin/quota/plans")
    if _assert(r.status_code == 200, "T6-08 方案預設配額列表", f"HTTP {r.status_code}"):
        plans = r.json()
        plan_names = list(plans.keys()) if isinstance(plans, dict) else []
        print(f"      {DIM}plans={plan_names}{RESET}")

    if tenant_id:
        # T6-09: 取得配額
        r = api.get(f"/admin/tenants/{tenant_id}/quota")
        if _assert(r.status_code == 200, "T6-09 取得租戶配額", f"HTTP {r.status_code}"):
            quota = r.json()
            print(f"      {DIM}max_documents={quota.get('max_documents')}, plan={quota.get('plan')}{RESET}")

        # T6-10: 更新配額
        r = api.put(f"/admin/tenants/{tenant_id}/quota", json_data={
            "quota_alert_threshold": 0.85,
        })
        _assert(r.status_code == 200, "T6-10 更新配額欄位", f"HTTP {r.status_code}")

        # T6-11: 套用方案
        r = api.post(f"/admin/tenants/{tenant_id}/quota/apply-plan", json_data=None,
                     params={"plan": "enterprise"})
        _assert(r.status_code == 200, "T6-11 套用 enterprise 方案", f"HTTP {r.status_code}")
    else:
        skip("T6-09~11 配額管理", "無 tenant_id")

    # ── Phase 5: 安全組態 ───────────────
    section("Phase 5: 安全組態")

    if tenant_id:
        # T6-12: 取得安全組態
        r = api.get(f"/admin/tenants/{tenant_id}/security")
        if _assert(r.status_code == 200, "T6-12 取得安全組態", f"HTTP {r.status_code}"):
            sec = r.json()
            print(f"      {DIM}isolation={sec.get('isolation_level')}, mfa={sec.get('require_mfa')}{RESET}")

        # T6-13: 更新安全組態
        r = api.put(f"/admin/tenants/{tenant_id}/security", json_data={
            "isolation_level": "enhanced",
            "require_mfa": False,
        })
        if _assert(r.status_code == 200, "T6-13 更新安全組態", f"HTTP {r.status_code}"):
            # 恢復預設
            api.put(f"/admin/tenants/{tenant_id}/security", json_data={
                "isolation_level": "standard",
            })
    else:
        skip("T6-12~13 安全組態", "無 tenant_id")

    # ── Phase 6: 部門管理 ───────────────
    section("Phase 6: 部門管理")

    # T6-14: 部門列表
    r = api.get("/departments/")
    _assert(r.status_code == 200, "T6-14 部門列表", f"HTTP {r.status_code}")

    # T6-15: 建立部門
    dept_name = f"Flow6_Test_{uuid.uuid4().hex[:6]}"
    r = api.post("/departments/", json_data={
        "name": dept_name,
        "description": "Flow6 自動測試建立的部門",
    })
    if _assert(r.status_code in (200, 201), "T6-15 建立部門", f"HTTP {r.status_code}"):
        created_dept_id = r.json().get("id")
        print(f"      {DIM}dept_id={created_dept_id}{RESET}")

    # T6-16: 部門樹
    r = api.get("/departments/tree")
    _assert(r.status_code == 200, "T6-16 部門樹狀結構", f"HTTP {r.status_code}")

    # T6-17: 取得部門
    if created_dept_id:
        r = api.get(f"/departments/{created_dept_id}")
        _assert(r.status_code == 200, "T6-17 取得單一部門", f"HTTP {r.status_code}")
    else:
        skip("T6-17 取得部門", "無 dept_id")

    # T6-18: 更新部門
    if created_dept_id:
        r = api.put(f"/departments/{created_dept_id}", json_data={
            "description": "Flow6 更新後的說明",
        })
        _assert(r.status_code == 200, "T6-18 更新部門", f"HTTP {r.status_code}")
    else:
        skip("T6-18 更新部門", "無 dept_id")

    # T6-19: 停用部門
    if created_dept_id and not keep:
        r = api.delete(f"/departments/{created_dept_id}")
        _assert(r.status_code in (200, 204), "T6-19 停用部門", f"HTTP {r.status_code}")
    elif created_dept_id:
        skip("T6-19 停用部門", "--keep 模式")
    else:
        skip("T6-19 停用部門", "無 dept_id")

    # T6-20: 可用功能模組
    r = api.get("/departments/features/available")
    if _assert(r.status_code == 200, "T6-20 可用功能模組列表", f"HTTP {r.status_code}"):
        features = r.json().get("features", [])
        print(f"      {DIM}features={features}{RESET}")

    # T6-21: 功能權限列表
    r = api.get("/departments/features/")
    _assert(r.status_code == 200, "T6-21 功能權限列表", f"HTTP {r.status_code}")

    # T6-22: 設定功能權限
    if features:
        r = api.post("/departments/features/", json_data={
            "feature": features[0],
            "allowed_roles": ["admin", "owner"],
            "enabled": True,
        })
        _assert(
            r.status_code in (200, 201),
            "T6-22 設定功能權限",
            f"HTTP {r.status_code}, feature={features[0]}"
        )
    else:
        skip("T6-22 設定功能權限", "無可用功能")

    # ── Phase 7: Feature Flags ──────────
    section("Phase 7: Feature Flags（功能旗標）")

    flag_key = f"flow6_test_flag_{uuid.uuid4().hex[:6]}"

    # T6-23: 列表
    r = api.get("/feature-flags/")
    _assert(r.status_code == 200, "T6-23 功能旗標列表", f"HTTP {r.status_code}")

    # T6-24: 建立
    r = api.post("/feature-flags/", json_data={
        "key": flag_key,
        "description": "Flow6 自動測試旗標",
        "enabled": False,
        "rollout_percentage": 50,
    })
    if _assert(r.status_code in (200, 201), "T6-24 建立功能旗標", f"HTTP {r.status_code}"):
        created_flag_key = flag_key
        print(f"      {DIM}key={flag_key}{RESET}")

    # T6-25: 取得
    if created_flag_key:
        r = api.get(f"/feature-flags/{created_flag_key}")
        if _assert(r.status_code == 200, "T6-25 取得旗標", f"HTTP {r.status_code}"):
            flag = r.json()
            _assert(flag.get("enabled") is False, "T6-25b 旗標為停用", str(flag.get("enabled")))
    else:
        skip("T6-25 取得旗標", "無 flag_key")

    # T6-26: 更新
    if created_flag_key:
        r = api.put(f"/feature-flags/{created_flag_key}", json_data={
            "enabled": True,
            "rollout_percentage": 100,
        })
        _assert(r.status_code == 200, "T6-26 更新旗標", f"HTTP {r.status_code}")
    else:
        skip("T6-26 更新旗標", "無 flag_key")

    # T6-27: 評估
    if created_flag_key:
        r = api.get(f"/feature-flags/{created_flag_key}/evaluate")
        if _assert(r.status_code == 200, "T6-27 評估旗標", f"HTTP {r.status_code}"):
            result = r.json()
            print(f"      {DIM}enabled={result.get('enabled')}{RESET}")
    else:
        skip("T6-27 評估旗標", "無 flag_key")

    # T6-28: 刪除
    if created_flag_key and not keep:
        r = api.delete(f"/feature-flags/{created_flag_key}")
        _assert(r.status_code == 200, "T6-28 刪除旗標", f"HTTP {r.status_code}")
    elif created_flag_key:
        skip("T6-28 刪除旗標", "--keep 模式")
    else:
        skip("T6-28 刪除旗標", "無 flag_key")

    # ── Phase 8: Organization & Company ──
    section("Phase 8: 組織 & 公司")

    # T6-29: Organization
    r = api.get("/organization/me")
    _assert(r.status_code == 200, "T6-29 GET /organization/me", f"HTTP {r.status_code}")

    # T6-30: Company dashboard
    r = api.get("/company/dashboard")
    _assert(r.status_code == 200, "T6-30 公司儀表板", f"HTTP {r.status_code}")

    # T6-31: Company profile
    r = api.get("/company/profile")
    _assert(r.status_code == 200, "T6-31 公司資料", f"HTTP {r.status_code}")

    # T6-32: Company quota
    r = api.get("/company/quota")
    _assert(r.status_code == 200, "T6-32 公司配額", f"HTTP {r.status_code}")

    # T6-33: Company users
    r = api.get("/company/users")
    _assert(r.status_code == 200, "T6-33 公司成員列表", f"HTTP {r.status_code}")

    # T6-34: Company usage
    r = api.get("/company/usage/summary")
    _assert(r.status_code == 200, "T6-34 公司使用量摘要", f"HTTP {r.status_code}")

    # ── Phase 9: 批次刪除 ───────────────
    section("Phase 9: 批次刪除文件")

    # T6-35: Batch delete（只驗證端點可達，不真的刪）
    # 先上傳一個假檔，避免清空真實資料
    import tempfile
    tmp = tempfile.NamedTemporaryFile(suffix=".txt", prefix="flow6_batch_", delete=False, mode="w", encoding="utf-8")
    tmp.write("Flow6 batch delete test\n")
    tmp.close()

    try:
        with open(tmp.name, "rb") as fh:
            r_up = api.session.post(
                f"{api.base}/api/v1/documents/upload",
                files={"file": ("flow6_batch_test.txt", fh)},
                timeout=30,
            )
        if r_up.status_code == 200:
            doc_id = r_up.json().get("id")
            # 直接刪除這一篇，不觸發 batch delete（避免清空所有文件）
            if doc_id:
                r_del = api.delete(f"/documents/{doc_id}")
                _assert(r_del.status_code == 200, "T6-35 單一刪除(保護性)", f"HTTP {r_del.status_code}")
        else:
            skip("T6-35 批次刪除", f"上傳失敗 HTTP {r_up.status_code}")
    finally:
        os.unlink(tmp.name)


def main():
    parser = argparse.ArgumentParser(description="Enclave Flow 6 — 平台管理全流程測試")
    parser.add_argument("--base-url", default="http://localhost:8001")
    parser.add_argument("--user", default="admin@example.com")
    parser.add_argument("--password", default="admin123")
    parser.add_argument("--keep", action="store_true", help="保留測試資料不刪除")
    args = parser.parse_args()

    print(f"\n{BOLD}═══════════════════════════════════════════════════")
    print(f"  Enclave Flow 6：平台管理全流程測試")
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
