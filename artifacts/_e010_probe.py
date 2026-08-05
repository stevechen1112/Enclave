"""直接打 chat stream，倒出 E010 的檢索來源與 trace。"""
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import httpx

BASE = "http://localhost:8001"
QUERIES = {
    "E010": "根據文件《000_nueip 合約(1).pdf》，出租系統的廠商名稱是什麼？",
}

client = httpx.Client(base_url=BASE, timeout=180.0)
r = client.post("/api/v1/auth/login/access-token",
                data={"username": "admin@example.com", "password": "admin123"})
client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

out = open("artifacts/_e010_probe_out.txt", "w", encoding="utf-8")
for qid, q in QUERIES.items():
    out.write(f"===== {qid}: {q}\n")
    with client.stream("POST", "/api/v1/chat/chat/stream",
                       json={"question": q, "conversation_id": None}) as resp:
        out.write(f"http {resp.status_code}\n")
        for line in resp.iter_lines():
            if not line or not line.startswith("data:"):
                continue
            try:
                d = json.loads(line[5:].strip())
            except Exception:
                continue
            t = d.get("type", "")
            if t == "retrieval":
                out.write("[retrieval] " + json.dumps(d, ensure_ascii=False)[:3000] + "\n")
            elif t == "sources":
                for s in d.get("sources", []):
                    out.write(f"[source] {s.get('title')} | score={s.get('score')} | "
                              f"provider={s.get('provider')} | chunk={s.get('chunk_index')} | "
                              f"snippet={s.get('snippet','')[:120]!r}\n")
            elif t in ("answer", "token", "content"):
                pass
            elif t == "done":
                ans = d.get("answer") or ""
                out.write(f"[answer] {ans[:500]}\n")
out.close()
print("done")
