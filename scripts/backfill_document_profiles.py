#!/usr/bin/env python3
"""Backfill capability profiles for existing active documents."""
from __future__ import annotations

from app.db.session import SessionLocal
from app.models.document import Document
from app.services.document_profile import upsert_document_profile


def main() -> int:
    db = SessionLocal()
    profiled = 0
    failed = []
    try:
        docs = db.query(Document).filter(
            Document.tombstoned_at.is_(None), Document.status == "completed"
        ).all()
        for doc in docs:
            try:
                text = "\n".join(
                    c.text or "" for c in sorted(doc.chunks, key=lambda x: x.chunk_index)
                )
                upsert_document_profile(db, doc, text, doc.quality_report or {})
                profiled += 1
            except Exception as exc:
                db.rollback()
                failed.append({"document_id": str(doc.id), "error_type": type(exc).__name__})
        db.commit()
        print({"active": len(docs), "profiled": profiled, "failed": failed})
        return 0 if not failed and profiled == len(docs) else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())

