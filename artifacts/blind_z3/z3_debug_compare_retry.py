import json
from pathlib import Path

import httpx

BASE = "http://localhost:8011"
CASES = [
    (
        "z3-v3-062",
        "安可系統開發報價調整版與味特報價暨合約，哪份總價較高？",
        ["696,500", "350,000"],
    ),
    (
        "z3-v3-064",
        "「委託合約-八策品牌」（客戶/安可）與「合約-八策數位股份有限公司」（八策內部）是否同一份文件？",
        ["安可日子", "Regus"],
    ),
]


def main() -> None:
    c = httpx.Client(base_url=BASE, timeout=httpx.Timeout(30.0, read=300.0))
    r = c.post(
        "/api/v1/auth/login/access-token",
        data={"username": "admin@enclave.local", "password": "admin123"},
    )
    r.raise_for_status()
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    out = {}
    for qid, q, need in CASES:
        print("ASK", qid, flush=True)
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
        hits = {n: (n in ans) for n in need}
        out[qid] = {"needles": hits, "answer": ans}
        print(" needles", hits, flush=True)
    path = Path("artifacts/blind_z3/z3_debug_compare_retry.json")
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("written", path)


if __name__ == "__main__":
    main()
