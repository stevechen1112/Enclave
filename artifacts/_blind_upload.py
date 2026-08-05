"""盲測文件上傳：走正式 /documents/upload API，與真實使用者路徑一致。"""
import io
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import httpx

BASE = "http://localhost:8001"

FILES = [
    r"C:\Users\User\Desktop\八策\113年營所稅申報書_E42八策.pdf",
    r"C:\Users\User\Desktop\八策\1140213-拉法(存奕官網)_報價單.docx",
    r"C:\Users\User\Downloads\吳文曄-履歷.pdf",
    r"C:\Users\User\Documents\巨大機械9921深度研究報告.pdf",
    r"C:\Users\User\Desktop\客戶\光昱金屬\亞馬遜行銷報價.pdf",
    r"C:\Users\User\Desktop\八策\政府補助\臺北市產業發展獎勵補助計畫申請簡介.pdf",
    r"C:\Users\User\Downloads\基礎操作教學手冊.pdf",
    r"C:\Users\User\Desktop\客戶\巽耘\【將能數位行銷】-巽耘法律事務所-健診報告.pdf",
]

client = httpx.Client(base_url=BASE, timeout=120.0)
r = client.post(
    "/api/v1/auth/login/access-token",
    data={"username": "admin@example.com", "password": "admin123"},
)
r.raise_for_status()
client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

for path in FILES:
    fn = path.split("\\")[-1]
    with open(path, "rb") as f:
        resp = client.post("/api/v1/documents/upload", files={"file": (fn, f)})
    if resp.status_code == 200:
        print("OK  ", fn, "->", resp.json().get("id"))
    else:
        print("FAIL", fn, resp.status_code, resp.text[:200])
    time.sleep(1)
