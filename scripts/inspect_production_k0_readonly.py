#!/usr/bin/env python3
"""Emit a privacy-preserving, read-only production corpus snapshot to stdout.

This operator probe is intentionally compatible with the pre-K1 production
image.  It uses metadata/count queries only, never selects document text,
emails, tokens or credentials, and never opens a write transaction.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter

from sqlalchemy import inspect, text

from app.db.session import SessionLocal


def _digest(values) -> str:
    return hashlib.sha256("\n".join(sorted(str(value) for value in values)).encode()).hexdigest()


def _count(db, table: str) -> int:
    return int(db.execute(text(f'SELECT count(*) FROM "{table}"')).scalar() or 0)


def main() -> int:
    db = SessionLocal()
    try:
        db.execute(text("SET TRANSACTION READ ONLY"))
        inspector = inspect(db.bind)
        tables = set(inspector.get_table_names())
        known = (
            "documents", "documentchunks", "knowledge_bases", "knowledge_base_revisions",
            "knowledge_base_members", "knowhow_cards", "retrievaltraces", "users",
            "connector_instances", "connector_resources", "source_acl_entries",
            "external_principals", "documentversions",
        )
        counts = {table: _count(db, table) for table in known if table in tables}
        documents = db.execute(text(
            "SELECT id, tenant_id, COALESCE(version, 1), COALESCE(content_hash, ''), "
            "COALESCE(status, ''), COALESCE(knowledge_base_id::text, ''), "
            "COALESCE(department_id::text, ''), COALESCE(source_system, ''), "
            "COALESCE(source_record_id, ''), tombstoned_at IS NOT NULL FROM documents"
        )).all() if "documents" in tables else []
        status_counts = Counter(str(row[4]) for row in documents)
        active = [row for row in documents if not row[9]]
        doc_tokens = [
            ":".join(str(value) for value in row[:9])
            for row in active
        ]
        acl_tokens = []
        if "knowledge_base_members" in tables:
            acl_tokens.extend(
                ":".join(str(value) for value in row)
                for row in db.execute(text(
                    "SELECT kb_id, subject_type, subject_id, role, effect FROM knowledge_base_members"
                )).all()
            )
        if "source_acl_entries" in tables:
            acl_tokens.extend(
                ":".join(str(value) for value in row)
                for row in db.execute(text(
                    "SELECT tenant_id, source_record_id, principal_id, effect FROM source_acl_entries"
                )).all()
            )
        tenant_ids = {str(row[1]) for row in documents}
        payload = {
            "privacy": "counts_and_digests_only",
            "database_tables_present": sorted(table for table in known if table in tables),
            "counts": counts,
            "document_status_counts": dict(sorted(status_counts.items())),
            "active_documents": len(active),
            "tenant_count_with_documents": len(tenant_ids),
            "tenant_set_digest": _digest(tenant_ids),
            "active_document_digest": _digest(doc_tokens),
            "acl_policy_digest": _digest(acl_tokens),
            "transaction_read_only": bool(db.execute(text("SHOW transaction_read_only")).scalar() == "on"),
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        db.rollback()
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
