"""z3_debug probe: re-ask z3-v3-067 after catalog CJK fix. Does NOT rewrite main set."""
from __future__ import annotations

import json
from pathlib import Path

import httpx

BASE = "http://localhost:8011"
OUT = Path(__file__).resolve().parent / "z3_debug_067.json"
Q = "這批資料裡，檔名或標題明顯出現「八策」的客戶／文件有哪些？列客戶或檔名。"
NEED = ["安可", "醫美圈圈", "八策"]


def stream_answer(client: httpx.Client, question: str) -> str:
    collected: list[str] = []
    with client.stream(
        "POST",
        "/api/v1/chat/chat/stream",
        json={"question": question},
        headers={"Accept": "text/event-stream"},
        timeout=httpx.Timeout(30.0, read=300.0),
    ) as resp:
        if resp.status_code != 200:
            return f"[ERROR {resp.status_code}] {resp.read().decode('utf-8', 'ignore')[:300]}"
        for raw in resp.iter_lines():
            if not raw:
                continue
            line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                d = json.loads(data)
            except json.JSONDecodeError:
                continue
            if d.get("type") == "token" and "content" in d:
                collected.append(d["content"])
            elif d.get("type") == "answer" and "content" in d:
                collected.append(d["content"])
    return "".join(collected)


def main() -> None:
    client = httpx.Client(base_url=BASE, timeout=httpx.Timeout(30.0, read=300.0))
    r = client.post(
        "/api/v1/auth/login/access-token",
        data={"username": "admin@enclave.local", "password": "admin123"},
    )
    r.raise_for_status()
    client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    ans = stream_answer(client, Q)
    hits = {n: (n in ans) for n in NEED}
    OUT.write_text(
        json.dumps({"query": Q, "needles": hits, "answer": ans}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print("needles", hits)
    print("written", OUT)
    print(ans[:800])


if __name__ == "__main__":
    main()
