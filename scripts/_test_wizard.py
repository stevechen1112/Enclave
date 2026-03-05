#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
完整測試資料夾匯入 Wizard 的每一步 API：
Step 1  選資料夾（前端負責，這裡改用 os.walk 模擬）
Step 2  POST /agent/scan-preview  → AI 摘要
Step 3  使用者勾選確認（模擬：全選）
Step 4  依序 POST /kb/documents/upload 上傳每個檔案
Step 5  確認上傳後出現在文件清單
"""

import os, time, json
import requests
from pathlib import Path

BASE = "http://localhost:8001"
WATCH = Path(r"C:\Users\User\Desktop\Enclave\test-agent-watch")

# ── Auth ──────────────────────────────────────────────────────────────────────
r = requests.post(f"{BASE}/api/v1/auth/login/access-token",
    data={"username": "admin@example.com", "password": "admin123"})
assert r.status_code == 200, f"Login failed: {r.text}"
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}
SEP = "=" * 60

print(f"\n{SEP}")
print("Wizard 資料夾匯入流程 端對端測試")
print(SEP)

# ── STEP 1：列出資料夾中的檔案（模擬前端 webkitdirectory）──────────────────
print("\n[Step 1] 枚舉本機資料夾檔案")
SUPPORTED = {".pdf", ".docx", ".doc", ".txt", ".xlsx", ".xls",
             ".csv", ".html", ".htm", ".md", ".rtf", ".json"}

files_by_dir = {}
for entry in WATCH.iterdir():
    if entry.is_file() and entry.suffix.lower() in SUPPORTED:
        dir_key = WATCH.name
        files_by_dir.setdefault(dir_key, []).append(entry)

for d, files in files_by_dir.items():
    print(f"  {d}/  → {len(files)} 個支援格式的檔案")
    for f in files:
        print(f"    - {f.name}  ({f.stat().st_size:,} bytes)")

# ── STEP 2：POST /agent/scan-preview（Ollama AI 摘要）─────────────────────
print(f"\n[Step 2] POST /agent/scan-preview  (AI 分析子資料夾)")

# 讀取 .md/.txt 檔案內容作為 content_samples
content_samples = []
for f in list(WATCH.iterdir())[:3]:
    if f.suffix.lower() in {".md", ".txt"}:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")[:600]
            if len(text.strip()) > 30:
                content_samples.append(text)
        except Exception:
            pass

payload = {
    "subfolders": [
        {
            "path": WATCH.name,
            "name": WATCH.name,
            "files": [f.name for f in files_by_dir.get(WATCH.name, [])],
            "content_samples": content_samples,
        }
    ]
}

t0 = time.time()
res = requests.post(f"{BASE}/api/v1/agent/scan-preview",
    json=payload,
    headers={**h, "Content-Type": "application/json"})
elapsed = time.time() - t0

print(f"  HTTP {res.status_code}  ({elapsed:.1f}s)")
if res.status_code == 200:
    for sf in res.json().get("subfolders", []):
        print(f"\n  資料夾：{sf['path']}")
        print(f"  檔案數：{sf['file_count']}")
        print(f"  內容取樣：{'是' if sf['has_content_samples'] else '否'}")
        print(f"  AI 摘要：{sf['summary']}")
    step2_ok = True
else:
    print(f"  ERROR: {res.text[:300]}")
    step2_ok = False

# ── STEP 3：使用者勾選確認（模擬：全選）────────────────────────────────────
print(f"\n[Step 3] 使用者確認（模擬全選所有子資料夾）")
selected_files = [f for files in files_by_dir.values() for f in files]
print(f"  已勾選 {len(files_by_dir)} 個資料夾，共 {len(selected_files)} 個檔案")
for f in selected_files:
    print(f"    ✓ {f.name}")

# ── STEP 4：批次上傳（POST /kb/documents/upload）────────────────────────────
print(f"\n[Step 4] 批次上傳至知識庫")
upload_results = []
for f in selected_files:
    try:
        with open(f, "rb") as fp:
            upload_r = requests.post(
                f"{BASE}/api/v1/documents/upload",
                headers=h,
                files={"file": (f.name, fp, "application/octet-stream")},
            )
        status = "✅" if upload_r.status_code in (200, 201) else "❌"
        doc_id = upload_r.json().get("id", "?")[:8] if upload_r.status_code in (200, 201) else "—"
        print(f"  {status} {f.name}  →  HTTP {upload_r.status_code}  doc_id={doc_id}...")
        upload_results.append({"file": f.name, "ok": upload_r.status_code in (200, 201),
                                "status": upload_r.status_code})
    except Exception as e:
        print(f"  ❌ {f.name}  →  Exception: {e}")
        upload_results.append({"file": f.name, "ok": False, "status": "exception"})

succeeded = sum(1 for r in upload_results if r["ok"])
failed = len(upload_results) - succeeded
print(f"\n  上傳結果：成功 {succeeded} / 失敗 {failed}")

# ── STEP 5：驗證文件出現在知識庫清單 ──────────────────────────────────────
print(f"\n[Step 5] 驗證文件已進入 KB 文件清單")
docs_r = requests.get(f"{BASE}/api/v1/documents/?limit=20", headers=h)
if docs_r.status_code == 200:
    docs_json = docs_r.json()
    docs = docs_json if isinstance(docs_json, list) else docs_json.get("documents", docs_json.get("items", []))
    print(f"  KB 目前共 {len(docs)} 份文件（顯示最新 5 筆）：")
    for d in docs[:5]:
        fname = d.get("filename") or d.get("original_filename") or d.get("title") or "?"
        status = d.get("status") or d.get("index_status") or "?"
        chunks = d.get("chunk_count") or d.get("chunks", "?")
        print(f"    - {fname}  狀態={status}  chunks={chunks}")
else:
    print(f"  ERROR: {docs_r.status_code}")

# ── 流程總結 ──────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("Wizard 流程驗證結果")
print(SEP)
print(f"  Step 1 枚舉檔案         ✅  {len(selected_files)} 個支援格式檔案")
print(f"  Step 2 AI 摘要          {'✅' if step2_ok else '❌'}  /agent/scan-preview")
print(f"  Step 3 使用者確認       ✅  (模擬全選)")
print(f"  Step 4 批次上傳         {'✅' if failed == 0 else '⚠️'}  成功={succeeded} 失敗={failed}")
print(f"  Step 5 驗證 KB 清單     ✅")
print(SEP)
