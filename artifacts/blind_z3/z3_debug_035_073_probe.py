"""z3_debug: 035 / 073 after named-file + guarantee guards."""
from __future__ import annotations

import json
from pathlib import Path

import httpx

BASE = "http://localhost:8011"
OUT = Path(__file__).resolve().parent / "z3_debug_035_073.json"
CASES = [
    {
        "id": "z3-v3-035",
        "q": "根目錄「行銷傳播企劃.pdf」主軸在談什麼？",
        "bad": ["Smat", "Color髮廊", "以消費者研究為基礎"],
        "good": ["無法", "沒有", "找不到", "未能"],
    },
    {
        "id": "z3-v3-073",
        "q": "醫美圈圈已用印報價保證哪一天官網上線？",
        "bad": ["2024 年 1 月 15 日", "2024年1月15日", "徵文活動"],
        "good": ["無法", "沒有", "保證", "拒絕"],
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
        out[case["id"]] = {
            "query": case["q"],
            "answer": ans,
            "has_good": any(g in ans for g in case["good"]),
            "has_bad": any(b in ans for b in case["bad"]),
        }
        print(
            "  good=", out[case["id"]]["has_good"],
            "bad=", out[case["id"]]["has_bad"],
            "head=", ans[:160].replace("\n", " | "),
            flush=True,
        )
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("written", OUT)


if __name__ == "__main__":
    main()
