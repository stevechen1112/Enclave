#!/usr/bin/env python3
"""Idempotently build the persistent lexical projection in bounded batches."""
from __future__ import annotations

import argparse
from uuid import UUID

from app.db.session import MaintenanceSessionLocal
from app.models.document import Document, DocumentChunk
from app.services.lexical_index import upsert_chunks
from app.services.rls import apply_rls_bypass, apply_rls_context


def backfill_tenant(db, *, tenant_id: UUID, batch_size: int) -> int:
    """Build one tenant's lexical projection without crossing its RLS scope."""
    apply_rls_context(db, tenant_id)
    total = 0
    docs = (
        db.query(Document)
        .filter(
            Document.tenant_id == tenant_id,
            Document.tombstoned_at.is_(None),
            Document.status == "completed",
        )
        .order_by(Document.id)
        .all()
    )
    for doc in docs:
        offset = 0
        while True:
            batch = (
                db.query(DocumentChunk)
                .filter(
                    DocumentChunk.tenant_id == tenant_id,
                    DocumentChunk.document_id == doc.id,
                )
                .order_by(DocumentChunk.chunk_index)
                .offset(offset)
                .limit(batch_size)
                .all()
            )
            if not batch:
                break
            total += upsert_chunks(db, batch, doc)
            db.commit()
            offset += len(batch)
    return total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch-size", type=int, default=500)
    ap.add_argument("--tenant-id", type=UUID)
    args = ap.parse_args()
    if args.batch_size < 1:
        ap.error("--batch-size must be at least 1")
    db = MaintenanceSessionLocal()
    try:
        if args.tenant_id:
            tenant_ids = [args.tenant_id]
        else:
            apply_rls_bypass(
                db,
                actor_identity="script:backfill_lexical_index",
                operation="discover_lexical_backfill_tenants",
                reason="Build missing lexical projections for completed knowledge documents",
            )
            tenant_ids = [
                row[0]
                for row in db.query(Document.tenant_id)
                .filter(
                    Document.tombstoned_at.is_(None),
                    Document.status == "completed",
                )
                .distinct()
                .all()
            ]
            db.commit()
        total = sum(
            backfill_tenant(db, tenant_id=tenant_id, batch_size=args.batch_size)
            for tenant_id in tenant_ids
        )
        print({"tenants": len(tenant_ids), "indexed_chunks": total})
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
