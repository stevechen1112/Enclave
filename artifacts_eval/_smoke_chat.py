"""快速冒煙：登入 + 問 3 題，確認 deps RLS wiring 與 storage 抽象不影響正常問答。"""
import io
import json
import os
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import httpx

BASE = "http://localhost:8001"

QUESTIONS = [
    ("事實題", "根據文件《113年營所稅申報書_E42八策.pdf》，納稅的公司名稱是什麼？"),
    ("清點題", "知識庫裡有哪些文件？"),
    ("拒答題", "根據文件《113年營所稅申報書_E42八策.pdf》，董事長的私人手機號碼是什麼？"),
]


def stream_answer(client, question, timeout=300):
    collected = []
    with client.stream("POST", "/api/v1/chat/chat/stream",
                       json={"question": question},
                       headers={"Accept": "text/event-stream"},
                       timeout=timeout) as resp:
        if resp.status_code != 200:
            return f"[ERROR {resp.status_code}]"
        for raw in resp.iter_lines():
            if not raw:
                continue
            line = raw if isinstance(raw, str) else raw.decode("utf-8")
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                d = json.loads(data)
            except json.JSONDecodeError:
                continue
            if d.get("type") == "token":
                collected.append(d.get("content", ""))
    return "".join(collected)


def main():
    client = httpx.Client(base_url=BASE, timeout=320.0)
    r = client.post("/api/v1/auth/login/access-token",
                    data={"username": os.environ["EVAL_ADMIN_EMAIL"],
                          "password": os.environ["EVAL_ADMIN_PASSWORD"]})
    r.raise_for_status()
    client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    print("login ok")

    for label, q in QUESTIONS:
        t0 = time.time()
        ans = stream_answer(client, q)
        print(f"\n=== {label} ({time.time()-t0:.0f}s) ===")
        print("A:", ans[:300])


if __name__ == "__main__":
    main()
