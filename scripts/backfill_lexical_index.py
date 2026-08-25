#!/usr/bin/env python3
"""Idempotently build the persistent lexical projection in bounded batches."""
from __future__ import annotations

import argparse

from app.db.session import SessionLocal
from app.models.document import Document, DocumentChunk
from app.services.lexical_index import upsert_chunks


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--batch-size", type=int, default=500)
    args = ap.parse_args(); db = SessionLocal(); total = 0
    try:
        docs = db.query(Document).filter(Document.tombstoned_at.is_(None), Document.status == "completed").yield_per(100)
        for doc in docs:
            offset = 0
            while True:
                batch = (db.query(DocumentChunk).filter(DocumentChunk.document_id == doc.id)
                         .order_by(DocumentChunk.chunk_index).offset(offset).limit(args.batch_size).all())
                if not batch: break
                total += upsert_chunks(db, batch, doc); db.commit(); offset += len(batch)
        print({"indexed_chunks": total})
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
