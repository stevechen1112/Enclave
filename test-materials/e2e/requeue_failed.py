"""重排 ingest_report.json 中失敗的文件（清除錯誤→重置狀態→重派任務→輪詢）。

用法：cd Enclave && python test-materials/e2e/requeue_failed.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

REPORT = Path(__file__).parent / "ingest_report.json"


def main() -> None:
    from app.db.session import SessionLocal
    from app.models.document import Document
    from app.tasks.document_tasks import process_document_task

    data = json.loads(REPORT.read_text(encoding="utf-8"))
    ids = [d for d in data["upload_ids"].values()
           if d and not str(d).startswith(("UPLOAD_FAIL", "NO_ID"))]
    print(f"requeue {len(ids)} docs")

    db = SessionLocal()
    try:
        for did in ids:
            doc = db.query(Document).filter(Document.id == did).first()
            if not doc:
                print(f"  {did[:8]} not found, skip")
                continue
            if doc.status == "completed":
                print(f"  {doc.filename}: already completed, skip")
                continue
            if not doc.file_path or not os.path.isfile(doc.file_path):
                print(f"  {doc.filename}: source missing ({doc.file_path}), skip")
                continue
            doc.status = "uploaded"
            doc.error_message = None
            db.commit()
            process_document_task.delay(
                document_id=str(doc.id),
                file_path=doc.file_path,
                tenant_id=str(doc.tenant_id),
            )
            print(f"  requeued {doc.filename}")
    finally:
        db.close()

    # 輪詢
    deadline = time.time() + 600
    pending = set(ids)
    final: dict[str, str] = {}
    while pending and time.time() < deadline:
        db = SessionLocal()
        try:
            for did in list(pending):
                doc = db.query(Document).filter(Document.id == did).first()
                if doc and doc.status in ("completed", "failed"):
                    final[doc.filename] = doc.status + (
                        f" ({doc.error_message[:80]})" if doc.error_message else "")
                    pending.discard(did)
                    print(f"  {doc.filename}: {doc.status}")
        finally:
            db.close()
        if pending:
            time.sleep(5)
    for did in pending:
        final[did] = "TIMEOUT"

    ok = sum(1 for v in final.values() if v.startswith("completed"))
    print(f"\n=== requeue done: {ok}/{len(ids)} completed ===")
    out = Path(__file__).parent / "requeue_report.json"
    out.write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
