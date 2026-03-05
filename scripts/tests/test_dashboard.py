import requests, time

BASE = "http://web:8000"

# Login as hr@taiyutech.com (has pre-loaded docs)
r = requests.post(f"{BASE}/api/v1/auth/login/access-token",
    data={"username": "hr@taiyutech.com", "password": "Test1234!"})
print(f"Login: {r.status_code}")
if r.status_code != 200:
    print(f"Login failed: {r.text[:200]}")
    exit(1)
token = r.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

def timed_chat(question, conv_id=None):
    payload = {"question": question, "top_k": 5}
    if conv_id:
        payload["conversation_id"] = conv_id
    t0 = time.time()
    first_token_time = None
    full = ""
    with requests.post(f"{BASE}/api/v1/chat/chat/stream",
                       headers=headers, json=payload, stream=True, timeout=60) as resp:
        for line in resp.iter_lines():
            if not line:
                continue
            if first_token_time is None:
                first_token_time = time.time() - t0
            line = line.decode()
            if line.startswith("data:"):
                import json
                try:
                    d = json.loads(line[5:])
                    if d.get("type") == "token":
                        full += d.get("content", "")
                    if d.get("type") == "done":
                        break
                except:
                    pass
    total = time.time() - t0
    print(f"  TTFB={first_token_time:.2f}s  Total={total:.2f}s  Chars={len(full)}")
    return resp.headers.get("X-Conversation-Id", ""), full[:80]

print("\n--- Round 1: 無代名詞（應跳過 contextualize） ---")
print("Q: 我們公司有交通津貼嗎？")
timed_chat("我們公司有交通津貼嗎？")

print("\n--- Round 2: 含代名詞「他」（應觸發 contextualize） ---")
print("Q1: E007 劉志明薪水多少？")
_, _ = timed_chat("E007 劉志明薪水多少？")
# need to get conversation id for follow-up
r_conv = requests.get(f"{BASE}/api/v1/chat/conversations", headers=headers)
conv_id = r_conv.json()[0]["id"] if r_conv.status_code == 200 else None
print(f"Q2: 他這個月加班費領了多少？(conv_id={str(conv_id)[:8]}...)")
timed_chat("他這個月加班費領了多少？", conv_id=conv_id)

# Test audit usage/by-action
r3 = requests.get(f"{BASE}/api/v1/audit/usage/by-action", headers=headers)
print(f"Audit usage/by-action: {r3.status_code}")
