"""Verify Phase 0 migration tables exist."""
from app.db.session import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    tables = [
        'knowledge_bases', 'knowledge_base_members', 'knowledge_base_revisions',
        'document_artifacts', 'outbox_events', 'projection_status',
        'sync_cursors', 'dead_letter_events',
    ]
    r = db.execute(text(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='public' AND table_name = ANY(:tables) "
        "ORDER BY table_name"
    ), {"tables": tables})
    found = [row[0] for row in r]
    print(f"Found {len(found)}/{len(tables)} tables:")
    for t in found:
        print(f"  OK  {t}")
    missing = set(tables) - set(found)
    for t in missing:
        print(f"  MISSING  {t}")

    # Check document columns
    r2 = db.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='documents' AND column_name IN "
        "('knowledge_base_id','source_system','source_record_id','content_hash','tombstoned_at')"
    ))
    doc_cols = [row[0] for row in r2]
    print(f"\nDocument new columns: {doc_cols}")
finally:
    db.close()
