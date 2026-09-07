from __future__ import annotations

from pathlib import Path


def test_tenant_scoped_backfill_establishes_rls_context_before_queries():
    root = Path(__file__).resolve().parents[1]
    script = (root / "scripts" / "backfill_knowledge_authority.py").read_text(
        encoding="utf-8"
    )

    context_index = script.index("apply_rls_context(db, args.tenant_id)")
    first_query_index = script.index("db.query(")

    assert context_index < first_query_index
    assert "MaintenanceSessionLocal" not in script
