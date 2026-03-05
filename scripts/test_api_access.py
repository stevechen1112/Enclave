#!/usr/bin/env python3
"""快速測試 API 可訪問性"""
import requests

BASE_URL = "http://api.172-237-5-254.sslip.io"

# 測試 1: Nginx 健康檢查
print(f"[1] 測試 {BASE_URL}/health")
try:
    r = requests.get(f"{BASE_URL}/health", timeout=10)
    print(f"  ✅ Status: {r.status_code}, Body: {r.text.strip()}")
except Exception as e:
    print(f"  ❌ Error: {e}")

# 測試 2: FastAPI 文檔
print(f"\n[2] 測試 {BASE_URL}/docs")
try:
    r = requests.get(f"{BASE_URL}/docs", timeout=10)
    print(f"  ✅ Status: {r.status_code}, FastAPI detected: {'FastAPI' in r.text}")
except Exception as e:
    print(f"  ❌ Error: {e}")

# 測試 3: OpenAPI schema
print(f"\n[3] 測試 {BASE_URL}/openapi.json")
try:
    r = requests.get(f"{BASE_URL}/openapi.json", timeout=10)
    print(f"  ✅ Status: {r.status_code}")
    data = r.json()
    print(f"  API Title: {data.get('info', {}).get('title')}")
    print(f"  Version: {data.get('info', {}).get('version')}")
    print(f"  Paths: {list(data.get('paths', {}).keys())[:5]}")
except Exception as e:
    print(f"  ❌ Error: {e}")

# 測試 4: 登入端點
print(f"\n[4] 測試登入端點")
try:
    r = requests.post(
        f"{BASE_URL}/api/v1/auth/login/access-token",
        data={
            "username": "admin@example.com",
            "password": "mcWzOEha0w7zKH9u53yG7Q"
        },
        timeout=10
    )
    print(f"  Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"  ✅ 登入成功! Token: {data.get('access_token', '')[:40]}...")
    else:
        print(f"  ❌ 登入失敗: {r.text[:200]}")
except Exception as e:
    print(f"  ❌ Error: {e}")
