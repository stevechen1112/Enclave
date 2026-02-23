#!/usr/bin/env python3
"""
aihr 生產環境輕量 Smoke Test
═══════════════════════════════════════════════
僅驗證 Linode 服務基本可用性（健康檢查 + 登入 + 文件列表 + 1 題問答）。

完整測試請使用 run_tests.py：
  AIHR_BASE_URL=http://api.172-237-5-254.sslip.io python scripts/run_tests.py
"""

import requests
import json
import time
import os
import sys

BASE_URL = os.getenv("AIHR_BASE_URL", "http://api.172-237-5-254.sslip.io")
SUPERUSER_EMAIL = os.getenv("AIHR_SUPERUSER_EMAIL", "admin@example.com")
SUPERUSER_PASSWORD = os.getenv("AIHR_SUPERUSER_PASS", "admin123")
HR_EMAIL = os.getenv("AIHR_HR_EMAIL", "hr@taiyutech.com")
HR_PASS = os.getenv("AIHR_HR_PASS", "Test1234!")
TIMEOUT = 30


def _req(method, path, token="", **kwargs):
    url = f"{BASE_URL}{path}"
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = requests.request(method, url, headers=headers, timeout=TIMEOUT, **kwargs)
        return r.json() if r.text else {}, r.status_code
    except Exception as e:
        return {"_error": str(e)}, 0


def main():
    print(f"{'='*50}")
    print(f"  aihr Smoke Test | {BASE_URL}")
    print(f"{'='*50}\n")

    checks = []

    # 1. Health
    d, st = _req("GET", "/health")
    ok = st == 200
    checks.append(("Health Check", ok))
    print(f"  {'✅' if ok else '❌'} Health: {st}")

    # 2. Superuser Login
    d, st = _req("POST", "/api/v1/auth/login/access-token",
                 data={"username": SUPERUSER_EMAIL, "password": SUPERUSER_PASSWORD})
    su_token = d.get("access_token", "")
    ok = st == 200 and bool(su_token)
    checks.append(("Superuser Login", ok))
    print(f"  {'✅' if ok else '❌'} Superuser Login: {st}")

    # 3. HR Login
    d, st = _req("POST", "/api/v1/auth/login/access-token",
                 data={"username": HR_EMAIL, "password": HR_PASS})
    hr_token = d.get("access_token", su_token)
    ok = st == 200 and bool(hr_token)
    checks.append(("HR Login", ok))
    print(f"  {'✅' if ok else '❌'} HR Login: {st}")

    token = hr_token or su_token

    # 4. Document List
    d, st = _req("GET", "/api/v1/documents/", token=token)
    count = len(d) if isinstance(d, list) else len(d.get("items", []))
    ok = st == 200
    checks.append(("Documents", ok))
    print(f"  {'✅' if ok else '❌'} Documents: {count} docs")

    # 5. Chat (1 question)
    t0 = time.time()
    d, st = _req("POST", "/api/v1/chat/chat", token=token,
                 json={"question": "公司加班費怎麼算？"})
    ms = int((time.time() - t0) * 1000)
    answer = d.get("answer", "")
    ok = st == 200 and len(answer) > 20
    checks.append(("Chat Q&A", ok))
    print(f"  {'✅' if ok else '❌'} Chat: {ms}ms, len={len(answer)}")

    # Summary
    passed = sum(1 for _, ok in checks if ok)
    total = len(checks)
    print(f"\n{'='*50}")
    print(f"  Smoke: {passed}/{total} passed")
    if passed == total:
        print("  ✅ 服務正常。完整測試請跑:")
        print(f"    AIHR_BASE_URL={BASE_URL} python scripts/run_tests.py")
    else:
        print("  ❌ 有基本問題需排查")
    print(f"{'='*50}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
