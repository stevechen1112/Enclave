import json

import httpx

BASE = "http://localhost:8011"
q = "捷報行銷提案報價的金額或方案價？"
c = httpx.Client(base_url=BASE, timeout=httpx.Timeout(30.0, read=180.0))
r = c.post(
    "/api/v1/auth/login/access-token",
    data={"username": "admin@enclave.local", "password": "admin123"},
)
c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
parts: list[str] = []
with c.stream(
    "POST",
    "/api/v1/chat/chat/stream",
    json={"question": q},
    headers={"Accept": "text/event-stream"},
) as resp:
    for raw in resp.iter_lines():
        if not raw:
            continue
        line = raw.decode() if isinstance(raw, bytes) else raw
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            d = json.loads(data)
        except json.JSONDecodeError:
            continue
        if d.get("type") in ("token", "answer") and "content" in d:
            parts.append(d["content"])
ans = "".join(parts)
print(ans[:800])
print("---")
print("has_refuse", any(m in ans for m in ["無法", "沒有", "找不到", "未收錄"]))
print("has_30000", "30,000" in ans or "30000" in ans)
