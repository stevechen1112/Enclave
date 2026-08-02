#!/usr/bin/env python3
"""DD-M04: report duplicate rows that would block unique-index migration.

Usage:
  python scripts/duplicate_constraint_report.py
  python scripts/duplicate_constraint_report.py --json artifacts/duplicate_report.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure repo root on path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


REPORT_QUERIES = {
    "documents_source_record": """
        SELECT tenant_id::text, source_system, source_record_id, COUNT(*) AS cnt
        FROM documents
        WHERE source_system IS NOT NULL
          AND source_record_id IS NOT NULL
          AND tombstoned_at IS NULL
        GROUP BY 1, 2, 3
        HAVING COUNT(*) > 1
        ORDER BY cnt DESC
        LIMIT 100
    """,
    "documentchunks_index": """
        SELECT document_id::text, chunk_index, COUNT(*) AS cnt
        FROM documentchunks
        GROUP BY 1, 2
        HAVING COUNT(*) > 1
        ORDER BY cnt DESC
        LIMIT 100
    """,
    "documentchunks_hash": """
        SELECT document_id::text, chunk_hash, COUNT(*) AS cnt
        FROM documentchunks
        WHERE chunk_hash IS NOT NULL
        GROUP BY 1, 2
        HAVING COUNT(*) > 1
        ORDER BY cnt DESC
        LIMIT 100
    """,
    "projection_status": """
        SELECT resource_type, resource_id, provider,
               COALESCE(provider_instance_id, '<null>') AS provider_instance_id,
               COUNT(*) AS cnt
        FROM projection_status
        GROUP BY 1, 2, 3, 4
        HAVING COUNT(*) > 1
        ORDER BY cnt DESC
        LIMIT 100
    """,
    "gateway_resources": """
        SELECT enclave_resource_type, enclave_resource_id, provider,
               COALESCE(provider_instance_id, '<null>') AS provider_instance_id,
               COUNT(*) AS cnt
        FROM gateway_resources
        GROUP BY 1, 2, 3, 4
        HAVING COUNT(*) > 1
        ORDER BY cnt DESC
        LIMIT 100
    """,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", dest="json_path", default=None)
    args = parser.parse_args()

    from sqlalchemy import text
    from app.db.session import SessionLocal

    db = SessionLocal()
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sections": {},
        "blocking": False,
    }
    try:
        for name, sql in REPORT_QUERIES.items():
            try:
                rows = db.execute(text(sql)).mappings().all()
                items = [dict(r) for r in rows]
            except Exception as exc:
                items = [{"error": str(exc)}]
            report["sections"][name] = {
                "duplicate_groups": len([i for i in items if "error" not in i]),
                "rows": items,
            }
            if any("error" not in i and i.get("cnt", 0) > 1 for i in items):
                report["blocking"] = True
    finally:
        db.close()

    text_out = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    if args.json_path:
        path = Path(args.json_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text_out, encoding="utf-8")
        print(f"wrote {path}")
    else:
        print(text_out)

    if report["blocking"]:
        print("BLOCKING: duplicates exist — repair before applying unique indexes", file=sys.stderr)
        return 2
    print("OK: no blocking duplicates detected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
