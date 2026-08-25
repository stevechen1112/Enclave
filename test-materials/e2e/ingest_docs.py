"""批次入庫 test-materials 文件至獨立、需驗證的 staging 驗收租戶。

用法：cd Enclave && python test-materials/e2e/ingest_docs.py
產出：test-materials/e2e/ingest_report.json
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

BASE = os.getenv("E2E_API_BASE", "http://127.0.0.1:8005/api/v1")
ADMIN_EMAIL = os.getenv("E2E_ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.environ["E2E_ADMIN_PASSWORD"]
TM = ROOT / "test-materials"
REPORT = Path(__file__).parent / "ingest_report.json"

# 入庫來源：自建文件全收；下載件只收可當通用知識的兩份 PDF
DIRS = ["shared", "A-sales", "B-field", "C-knowhow"]
EXTRA_FILES = [
    TM / "_downloads" / "D07_工具機作業安全作業標準_宜蘭大學.pdf",
    TM / "_downloads" / "ref_機械完整性管理程序參考手冊_勞動部.pdf",
]
SKIP_NAMES = {"QR_場景註冊資料.md"}  # 設定說明文件，不入庫
SKIP_SUFFIX = {".py"}


def main() -> None:
    files: list[Path] = []
    for d in DIRS:
        files.extend(sorted((TM / d).glob("*")))
    files.extend(EXTRA_FILES)
    files = [
        f for f in files
        if f.is_file() and f.suffix.lower() not in SKIP_SUFFIX and f.name not in SKIP_NAMES
    ]
    print(f"準備上傳 {len(files)} 個檔案")

    with httpx.Client(base_url=BASE, timeout=120.0) as client:
        r = client.post("/auth/login/access-token",
                        data={"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        r.raise_for_status()
        headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

        uploaded: dict[str, str] = {}
        for fpath in files:
            with open(fpath, "rb") as f:
                r = client.post("/documents/upload", headers=headers,
                                files={"file": (fpath.name, f)})
                if r.status_code not in (200, 201, 202):
                    print(f"FAIL upload {fpath.name}: {r.status_code} {r.text[:200]}")
                    uploaded[fpath.name] = f"UPLOAD_FAIL:{r.status_code}"
                    continue
            body = r.json()
            did = body.get("id") or body.get("document_id")
            uploaded[fpath.name] = did or "NO_ID"
            print(f"uploaded {fpath.name} -> {did}")

        # 輪詢狀態
        deadline = time.time() + 600
        pending = {n: d for n, d in uploaded.items() if d and not str(d).startswith(("UPLOAD_FAIL", "NO_ID"))}
        final: dict[str, str] = {}
        while pending and time.time() < deadline:
            for name, did in list(pending.items()):
                d = client.get(f"/documents/{did}", headers=headers)
                if d.status_code != 200:
                    continue
                st = d.json().get("status")
                if st in ("completed", "failed"):
                    final[name] = st
                    del pending[name]
                    print(f"  {name}: {st}")
            if pending:
                time.sleep(4)
        for name in pending:
            final[name] = "TIMEOUT"

    ok = sum(1 for v in final.values() if v == "completed")
    report = {"total": len(uploaded), "completed": ok, "detail": final,
              "upload_ids": uploaded}
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n=== ingest done: {ok}/{len(uploaded)} completed ===")
    print(f"report: {REPORT}")


if __name__ == "__main__":
    main()
