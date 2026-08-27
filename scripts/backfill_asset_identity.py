#!/usr/bin/env python3
"""Backfill legacy Documents into SourceAsset in bounded tenant-scoped batches.

Usage:
  python scripts/backfill_asset_identity.py --tenant-id <uuid> --dry-run
  python scripts/backfill_asset_identity.py --tenant-id <uuid> --batch-size 500
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from uuid import UUID

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill one tenant's legacy Documents into canonical assets"
    )
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    tenant_id = UUID(args.tenant_id)
    batch_size = max(1, min(int(args.batch_size), 5000))

    from app.db.session import SessionLocal
    from app.services.asset_projection import backfill_document_assets
    from app.services.rls import apply_rls_context

    db = SessionLocal()
    totals = {
        "documents_scanned": 0,
        "assets_created": 0,
        "revisions_created": 0,
        "pending_source_bytes": 0,
        "batches": 0,
    }
    try:
        apply_rls_context(db, tenant_id)
        while True:
            result = backfill_document_assets(db, tenant_id=tenant_id, limit=batch_size)
            totals["batches"] += 1
            for key in (
                "documents_scanned",
                "assets_created",
                "revisions_created",
                "pending_source_bytes",
            ):
                totals[key] += result[key]
            if args.dry_run:
                db.rollback()
                break
            db.commit()
            if result["documents_scanned"] < batch_size:
                break
        print(json.dumps({"tenant_id": str(tenant_id), **totals}, indent=2))
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
