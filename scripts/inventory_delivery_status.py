"""FD-DELIVER — 入庫交付不變量閘門（ADR-010），存量清冊＋判定。

掃描全部非刪除文件，分類交付缺陷：

- `delivery_false_completed`（硬違規）：scan 路由（ragflow_deepdoc/vlm）
  status=completed 但 parse_engine=native/text_fallback —— 假完成。
- `delivery_completed_without_evidence`（硬違規）：completed 但
  quality_report 缺失或 chunk 數為 0 —— 無交付證據。
- `delivery_stuck`（硬違規）：status 停在 uploaded/parsing/embedding 超過
  --stuck-hours（預設 1 小時）。
- `delivery_failed_actionable`（清冊）：failed 且 error_message 非空——
  允許存在（誠實失敗），但列入待重跑清冊。
- `delivery_failed_silent`（硬違規）：failed 卻無 error_message。
- `delivery_partial_sync`（硬違規）：completed 且走 RAGFlow 同步（無雲端 OCR
  救援），但 Enclave chunk 文本總字數 < RAGFlow 端 chunk 文本總字數的 80% ——
  部分同步假完成（2026-08-03 E010 根因：nueip 合約 completed 但只同步到
  1 個 chunk 的文本）。注意：Enclave 會把 RAGFlow chunks 接合後重新切塊，
  所以比對「字數」而非「chunk 數」（chunk 數差異是設計使然）。

PASS 條件：無任何硬違規。清冊（failed_actionable）不阻斷 PASS，但必須出現在
artifact 供重跑腳本使用。RAGFlow 對帳需 RAGFLOW_API_KEY；無法連線時記
`reconcile_skipped` 並在 artifact 誠實標註（不當 PASS 也不當 FAIL 的理由）。

Usage:
  set POSTGRES_SERVER=localhost & set POSTGRES_PORT=5435 & python scripts/inventory_delivery_status.py
  python scripts/inventory_delivery_status.py --stuck-hours 1
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "foundation_delivery_last_run.json"

SCAN_ROUTES = ("ragflow_deepdoc", "ragflow_vlm")
ACTIVE_STATUSES = ("uploaded", "parsing", "embedding", "processing", "pending")


def _db_url() -> str:
    url = os.getenv("DATABASE_URL", "")
    if url:
        return url.replace("postgresql+asyncpg://", "postgresql://")
    return (f"postgresql://{os.getenv('POSTGRES_USER', 'postgres')}"
            f":{os.getenv('POSTGRES_PASSWORD', 'postgres')}"
            f"@{os.getenv('POSTGRES_SERVER', 'localhost')}"
            f":{os.getenv('POSTGRES_PORT', '5435')}"
            f"/{os.getenv('POSTGRES_DB', 'enclave')}")


def _ragflow_conf() -> tuple[str, str, str]:
    """RAGFlow 連線設定；env 缺失時回退讀 .env（與 repo 其他腳本一致）。"""
    def _from_dotenv(key: str) -> str:
        env_path = ROOT / ".env"
        if not env_path.exists():
            return ""
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
        return ""

    base = os.getenv("RAGFLOW_BASE_URL") or _from_dotenv("RAGFLOW_BASE_URL") \
        or "http://localhost:9380"
    key = os.getenv("RAGFLOW_API_KEY") or _from_dotenv("RAGFLOW_API_KEY")
    ds = os.getenv("RAGFLOW_DATASET_ID") or _from_dotenv("RAGFLOW_DATASET_ID")
    return base.rstrip("/"), key, ds


def _ragflow_chunk_chars(base: str, api_key: str, dataset_id: str,
                         ragflow_doc_id: str, timeout: float = 15.0) -> int | None:
    """查 RAGFlow 端該文件所有 chunk 的文本總字數（分頁取全量）；失敗回 None。"""
    try:
        import httpx
    except ImportError:
        return None
    total_chars = 0
    page = 1
    try:
        with httpx.Client(timeout=timeout) as client:
            while True:
                resp = client.get(
                    f"{base}/api/v1/datasets/{dataset_id}/documents/{ragflow_doc_id}/chunks",
                    headers={"Authorization": f"Bearer {api_key}"},
                    params={"page": page, "page_size": 100},
                )
                if resp.status_code != 200:
                    return None
                data = resp.json().get("data") or {}
                chunks = data.get("chunks", []) if isinstance(data, dict) else data
                if not chunks:
                    break
                for c in chunks:
                    total_chars += len(c.get("content") or c.get("content_with_weight") or "")
                if len(chunks) < 100:
                    break
                page += 1
        return total_chars
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stuck-hours", type=float, default=1.0)
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    try:
        from sqlalchemy import create_engine, text as sql_text
    except ImportError:
        print("sqlalchemy unavailable", file=sys.stderr)
        return 2

    engine = create_engine(_db_url(), pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            rows = conn.execute(sql_text("""
                SELECT d.id, d.filename, d.file_type, d.status, d.error_message,
                       d.quality_report, d.created_at, d.updated_at,
                       (SELECT count(*) FROM documentchunks dc
                        WHERE dc.document_id = d.id) AS chunks,
                       (SELECT coalesce(sum(length(dc.text)), 0) FROM documentchunks dc
                        WHERE dc.document_id = d.id) AS chunk_chars
                FROM documents d
                WHERE d.status != 'deleted' AND d.tombstoned_at IS NULL
                ORDER BY d.filename
            """)).fetchall()
    except Exception as exc:
        report = {
            "gate": "FD-DELIVER", "schema_version": 1,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "status": "BLOCKED",
            "contract_violations": [f"db_unreachable: {type(exc).__name__}: {exc}"],
            "summary": {}, "cases": [],
        }
        pathlib.Path(args.out).write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print("BLOCKED:", exc)
        return 2

    now = datetime.now(timezone.utc)
    stuck_cutoff = now - timedelta(hours=args.stuck_hours)

    cases: list[dict] = []
    violations: list[str] = []
    reingest_candidates: list[dict] = []

    for r in rows:
        (doc_id, filename, file_type, status, error, qr,
         created_at, updated_at, chunks, chunk_chars) = r
        if isinstance(qr, str):
            try:
                qr = json.loads(qr)
            except json.JSONDecodeError:
                qr = None
        qr = qr if isinstance(qr, dict) else {}
        engine_label = str(qr.get("parse_engine") or "")
        route = str(qr.get("parse_route") or "")

        case = {"id": str(doc_id), "filename": filename, "status": status,
                "parse_engine": engine_label or None, "parse_route": route or None,
                "chunks": chunks, "chunk_chars": int(chunk_chars or 0),
                "error": (error or "")[:300] or None,
                "classification": "ok", "violation": None}

        if status == "completed" and engine_label == "native/text_fallback" \
                and route in SCAN_ROUTES:
            case["classification"] = "false_completed"
            case["violation"] = "delivery_false_completed"
            violations.append(
                f"delivery_false_completed: {filename} ({str(doc_id)[:8]}) "
                f"completed with native/text_fallback on scan route")
            reingest_candidates.append({"id": str(doc_id), "filename": filename,
                                        "reason": "false_completed"})
        elif status == "completed" and (not qr or chunks == 0):
            case["classification"] = "completed_without_evidence"
            case["violation"] = "delivery_completed_without_evidence"
            violations.append(
                f"delivery_completed_without_evidence: {filename} ({str(doc_id)[:8]}) "
                f"completed but quality_report={'null' if not qr else 'present'}, chunks={chunks}")
            reingest_candidates.append({"id": str(doc_id), "filename": filename,
                                        "reason": "completed_without_evidence"})
        elif status in ACTIVE_STATUSES:
            ts = updated_at or created_at
            if ts is not None and ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts is None or ts < stuck_cutoff:
                case["classification"] = "stuck"
                case["violation"] = "delivery_stuck"
                violations.append(
                    f"delivery_stuck: {filename} ({str(doc_id)[:8]}) "
                    f"status={status} since {ts}")
                reingest_candidates.append({"id": str(doc_id), "filename": filename,
                                            "reason": f"stuck_{status}"})
        elif status == "failed":
            if (error or "").strip():
                case["classification"] = "failed_actionable"
                reingest_candidates.append({"id": str(doc_id), "filename": filename,
                                            "reason": "failed_actionable"})
            else:
                case["classification"] = "failed_silent"
                case["violation"] = "delivery_failed_silent"
                violations.append(
                    f"delivery_failed_silent: {filename} ({str(doc_id)[:8]}) "
                    f"failed without error_message")

        cases.append(case)

    # ── RAGFlow 對帳：completed 且無雲端 OCR 救援的文件，Enclave chunk 文本
    # 總字數不得低於 RAGFlow 端 80%（Enclave 會接合後重新切塊，故比字數而非
    # chunk 數）；低於門檻即部分同步假完成（delivery_partial_sync）。
    reconcile_note = None
    rf_base, rf_key, rf_ds = _ragflow_conf()
    if not (rf_key and rf_ds):
        reconcile_note = "reconcile_skipped: missing RAGFLOW_API_KEY or RAGFLOW_DATASET_ID"
    else:
        for case, r in zip(cases, rows):
            if case["status"] != "completed" or case["violation"]:
                continue
            qr = r[5]
            if isinstance(qr, str):
                try:
                    qr = json.loads(qr)
                except json.JSONDecodeError:
                    qr = None
            qr = qr if isinstance(qr, dict) else {}
            rf_ids = qr.get("ragflow_doc_ids") or []
            if not rf_ids or qr.get("cloud_ocr"):
                continue
            rf_chars = _ragflow_chunk_chars(rf_base, rf_key, rf_ds, str(rf_ids[0]))
            if rf_chars is None:
                reconcile_note = "reconcile_partial: some RAGFlow lookups failed"
                continue
            case["ragflow_chunk_chars"] = rf_chars
            if rf_chars > 0 and case["chunk_chars"] < 0.8 * rf_chars:
                case["classification"] = "partial_sync"
                case["violation"] = "delivery_partial_sync"
                violations.append(
                    f"delivery_partial_sync: {case['filename']} ({case['id'][:8]}) "
                    f"enclave_chars={case['chunk_chars']} < 80% of ragflow_chars={rf_chars}")
                reingest_candidates.append({"id": case["id"], "filename": case["filename"],
                                            "reason": "partial_sync"})

    summary = {
        "total_active_docs": len(cases),
        "ok": sum(1 for c in cases if c["classification"] == "ok"),
        "false_completed": sum(1 for c in cases if c["classification"] == "false_completed"),
        "completed_without_evidence": sum(1 for c in cases if c["classification"] == "completed_without_evidence"),
        "stuck": sum(1 for c in cases if c["classification"] == "stuck"),
        "failed_actionable": sum(1 for c in cases if c["classification"] == "failed_actionable"),
        "failed_silent": sum(1 for c in cases if c["classification"] == "failed_silent"),
        "partial_sync": sum(1 for c in cases if c["classification"] == "partial_sync"),
    }
    report = {
        "gate": "FD-DELIVER", "schema_version": 1,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "method": "DB inventory of non-deleted documents vs ADR-010 delivery invariants",
        "status": "PASS" if not violations else "FAIL",
        "contract_violations": violations,
        "summary": summary,
        "reconcile_note": reconcile_note,
        "reingest_candidates": reingest_candidates,
        "cases": cases,
    }
    pathlib.Path(args.out).write_text(
        json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("status:", report["status"], "| summary:", json.dumps(summary, ensure_ascii=False))
    for v in violations:
        print("  VIOLATION:", v)
    print("written:", args.out)
    return 0 if not violations else 1


if __name__ == "__main__":
    sys.exit(main())
