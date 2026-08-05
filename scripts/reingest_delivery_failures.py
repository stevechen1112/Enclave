"""F1 — 重跑入庫交付失敗／假完成文件（ADR-010 存量收斂）。

對象（預設讀取 artifacts/foundation_delivery_last_run.json 的 reingest_candidates，
或加 --all-failed 自行查 DB）：

1. 源檔不存在 → 標 failed + 可行動 error_message（不得靜默）。
2. 源檔存在 → 刪除舊 chunks／artifacts（避免 text_fallback 殘留污染索引），
   重設狀態，重排 process_document_task，輪詢至終態。

必須在 worker 容器內執行（需 celery broker 與檔案系統路徑）：

  docker compose restart worker   # 先載入最新 parse_pipeline
  docker compose exec worker python scripts/reingest_delivery_failures.py

產出：artifacts/delivery_reingest_last_run.json
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
from uuid import UUID

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "delivery_reingest_last_run.json"
INVENTORY = ROOT / "artifacts" / "foundation_delivery_last_run.json"

sys.path.insert(0, str(ROOT))


def _load_candidates(from_inventory: bool) -> list[dict]:
    if from_inventory and INVENTORY.exists():
        data = json.loads(INVENTORY.read_text(encoding="utf-8"))
        return data.get("reingest_candidates") or []

    from sqlalchemy import create_engine, text as sql_text
    from app.config import settings
    url = (f"postgresql+psycopg2://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
           f"@{settings.POSTGRES_SERVER}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}")
    eng = create_engine(url)
    with eng.connect() as c:
        rows = c.execute(sql_text("""
            SELECT d.id, d.filename, d.status, d.quality_report
            FROM documents d
            WHERE d.status != 'deleted' AND d.tombstoned_at IS NULL
              AND (
                d.status IN ('failed', 'uploaded', 'parsing', 'embedding')
                OR (d.status = 'completed' AND (
                      d.quality_report IS NULL
                      OR d.quality_report->>'parse_engine' = 'native/text_fallback'
                      OR (SELECT count(*) FROM documentchunks dc
                          WHERE dc.document_id = d.id) = 0
                ))
              )
        """)).fetchall()
    out = []
    for r in rows:
        reason = ("failed_actionable" if r[2] == "failed"
                  else f"stuck_{r[2]}" if r[2] != "completed"
                  else "false_completed_or_no_evidence")
        out.append({"id": str(r[0]), "filename": r[1], "reason": reason})
    return out


GOLDEN_DIR = ROOT / "testdata" / "golden" / "files"


def _resolve_source(doc_id: str, filename: str, content_hash: str | None) -> tuple[str | None, str]:
    """Locate the real source bytes for a document.

    Order: uploads dir → golden files (exact name, then prefix-stripped match).
    Golden matches require content_hash equality when the doc has one on record,
    so we never re-ingest bytes that differ from what the user uploaded.
    Returns (path, provenance).
    """
    up = ROOT / "uploads" / doc_id
    if up.is_dir():
        files = [p for p in up.iterdir() if p.is_file()]
        if files:
            return str(files[0]), "uploads_dir"

    if GOLDEN_DIR.is_dir() and filename:
        exact = GOLDEN_DIR / filename
        candidates = [exact] if exact.exists() else [
            p for p in GOLDEN_DIR.iterdir()
            if p.is_file() and (p.name.endswith(filename) or filename.endswith(p.name))
        ]
        import hashlib
        for cand in candidates:
            if content_hash and content_hash.startswith("sha256:"):
                h = "sha256:" + hashlib.sha256(cand.read_bytes()).hexdigest()
                if h != content_hash:
                    continue
            return str(cand), f"golden_files:{cand.name}"
    return None, "source_not_found"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all-failed", action="store_true",
                    help="query DB directly instead of reading the inventory artifact")
    ap.add_argument("--timeout-s", type=int, default=900,
                    help="per-document wait budget (cloud OCR on big scans is slow)")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    from sqlalchemy import create_engine, text as sql_text
    from app.config import settings
    from app.tasks.document_tasks import process_document_task

    url = (f"postgresql+psycopg2://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
           f"@{settings.POSTGRES_SERVER}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}")
    eng = create_engine(url)

    candidates = _load_candidates(from_inventory=not args.all_failed)
    print(f"candidates: {len(candidates)}")

    results = []
    t0 = time.time()
    for cand in candidates:
        doc_id = cand["id"]
        entry = {"id": doc_id, "filename": cand["filename"],
                 "reason": cand["reason"], "action": None, "final_status": None}
        with eng.begin() as c:
            row = c.execute(sql_text(
                "SELECT file_path, file_type, tenant_id, status, content_hash "
                "FROM documents "
                "WHERE id = :i AND status != 'deleted' AND tombstoned_at IS NULL"
            ), {"i": doc_id}).fetchone()
        if not row:
            entry["action"] = "skip_not_found_or_deleted"
            results.append(entry)
            continue

        file_path, file_type, tenant_id, prev_status, content_hash = row
        entry["previous_status"] = prev_status

        if not file_path or not os.path.exists(file_path):
            resolved, provenance = _resolve_source(doc_id, cand["filename"], content_hash)
            entry["source_provenance"] = provenance
            if resolved:
                file_path = resolved
                with eng.begin() as c:
                    c.execute(sql_text(
                        "UPDATE documents SET file_path=:p WHERE id=:i"
                    ), {"p": file_path, "i": doc_id})
            else:
                with eng.begin() as c:
                    c.execute(sql_text(
                        "UPDATE documents SET status='failed', error_message=:e "
                        "WHERE id=:i"
                    ), {"e": ("入庫交付失敗：源檔案不存在於儲存層"
                              "（uploads 與黃金集皆無符合內容雜湊的來源）——"
                              "可能為測試殘留或已被外部清除；請重新上傳或刪除此文件記錄。"),
                        "i": doc_id})
                entry["action"] = "marked_failed_source_missing"
                entry["final_status"] = "failed"
                results.append(entry)
                print(f"{cand['filename']}: source missing → failed (actionable)", flush=True)
                continue

        # 清掉舊 chunks／artifacts，避免 text_fallback 殘留與新 chunk 並存污染索引
        with eng.begin() as c:
            deleted_chunks = c.execute(sql_text(
                "DELETE FROM documentchunks WHERE document_id = :i"
            ), {"i": doc_id}).rowcount
            c.execute(sql_text(
                "DELETE FROM document_artifacts WHERE document_id = :i"
            ), {"i": doc_id})
            c.execute(sql_text(
                "UPDATE documents SET status='uploaded', error_message=NULL, "
                "chunk_count=0 WHERE id=:i"
            ), {"i": doc_id})
        entry["deleted_old_chunks"] = deleted_chunks
        entry["action"] = "requeued"
        process_document_task.delay(doc_id, file_path, str(tenant_id))

        deadline = time.time() + args.timeout_s
        final = None
        while time.time() < deadline:
            with eng.connect() as c:
                st = c.execute(sql_text(
                    "SELECT status, error_message, chunk_count, "
                    "quality_report->>'parse_engine' FROM documents WHERE id=:i"
                ), {"i": doc_id}).fetchone()
            if st and st[0] in ("completed", "failed"):
                final = st
                break
            time.sleep(5)
        if final:
            entry["final_status"] = final[0]
            entry["error"] = (final[1] or "")[:300] or None
            entry["chunk_count"] = final[2]
            entry["parse_engine"] = final[3]
        else:
            entry["final_status"] = "timeout_waiting"
        results.append(entry)
        print(f"{cand['filename']}: {prev_status} → {entry['final_status']} "
              f"(engine={entry.get('parse_engine')}, chunks={entry.get('chunk_count')})",
              flush=True)

    summary = {
        "total": len(results),
        "completed": sum(1 for r in results if r["final_status"] == "completed"),
        "failed": sum(1 for r in results if r["final_status"] == "failed"),
        "other": sum(1 for r in results if r["final_status"] not in ("completed", "failed")),
    }
    report = {
        "gate": "FD-DELIVER-REINGEST",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "elapsed_s": round(time.time() - t0, 1),
        "summary": summary,
        "results": results,
    }
    pathlib.Path(args.out).write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\nsummary:", json.dumps(summary, ensure_ascii=False))
    print("written:", args.out)
    return 0 if summary["other"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
