"""z3_debug: cross-file compare probes after QueryPlan 1.3."""
from __future__ import annotations

import json
from pathlib import Path

import httpx

BASE = "http://localhost:8011"
OUT = Path(__file__).resolve().parent / "z3_debug_compare.json"
CASES = [
    {
        "id": "z3-v3-062",
        "q": "安可系統開發報價調整版與味特報價暨合約，哪份總價較高？",
        "need": ["696,500", "350,000"],
    },
    {
        "id": "z3-v3-064",
        "q": "「委託合約-八策品牌」（客戶/安可）與「合約-八策數位股份有限公司」（八策內部）是否同一份文件？",
        "need": ["安可日子", "Regus"],
    },
    {
        "id": "z3-v3-065",
        "q": "地政醫院行銷網站報價與立壕設計報價，哪份較高？",
        "need": ["60,000", "11,550"],
    },
    {
        "id": "z3-v3-070",
        "q": "請列出這批中檔名含「行銷提案」的客戶名稱（至少三個）。",
        "need": ["Color", "街道沙龍"],
    },
]


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
            return f"[ERROR {resp.status_code}] {resp.read().decode('utf-8', 'ignore')[:400]}"
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
            if d.get("type") in ("token", "answer") and "content" in d:
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
    out = {}
    for case in CASES:
        print("ASK", case["id"], flush=True)
        ans = stream_answer(client, case["q"])
        hits = {n: (n in ans) for n in case["need"]}
        out[case["id"]] = {"needles": hits, "answer": ans}
        print("  needles", hits, flush=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("written", OUT)


if __name__ == "__main__":
    main()
