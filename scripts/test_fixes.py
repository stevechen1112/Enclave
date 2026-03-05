"""Test specific queries to verify retrieval fixes."""
import requests, json, time

BASE_URL = "http://localhost:8001"

token = requests.post(f"{BASE_URL}/api/v1/auth/login/access-token",
    data={"username": "admin@example.com", "password": "admin123"}).json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

tests = [
    ("績效考核", "王俊傑今年績效考核結果是幾分？什麼等級？", ["97", "S"]),
    ("健康管理", "王俊傑的健康檢查有哪些異常項目？", ["異常", "王俊傑"]),
]

for cat, q, keywords in tests:
    t0 = time.time()
    r = requests.post(f"{BASE_URL}/api/v1/chat/chat", headers=headers, json={"question": q})
    elapsed = time.time() - t0
    data = r.json()
    answer = data.get("answer", "")
    sources = [s.get("title", "?") for s in data.get("sources", [])]
    hits = sum(1 for kw in keywords if kw in answer)
    score_pct = int(hits / len(keywords) * 100)
    print(f"[{cat}]")
    print(f"  命中: {hits}/{len(keywords)} ({score_pct}%) | {elapsed:.2f}s")
    print(f"  來源: {', '.join(sources)}")
    print(f"  回答: {answer[:200]}")
    print()
