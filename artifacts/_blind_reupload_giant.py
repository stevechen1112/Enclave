"""刪除並重新上傳巨大機械報告（驗證 RAGFlow 同步競態修復）。"""
import io
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import httpx

BASE = "http://localhost:8001"
DOC_ID = "46fd0149-0870-44f8-b22b-e445d969c734"
SRC = r"C:\Users\User\Documents\巨大機械9921深度研究報告.pdf"

client = httpx.Client(base_url=BASE, timeout=120.0)
r = client.post("/api/v1/auth/login/access-token",
                data={"username": "admin@example.com", "password": "admin123"})
r.raise_for_status()
client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

d = client.delete(f"/api/v1/documents/{DOC_ID}")
print("delete:", d.status_code, d.text[:150])
time.sleep(3)

with open(SRC, "rb") as f:
    up = client.post("/api/v1/documents/upload",
                     files={"file": ("巨大機械9921深度研究報告.pdf", f)})
print("upload:", up.status_code, up.json().get("id") if up.status_code == 200 else up.text[:200])
