"""Sync existing clause_projection artifacts to Enclave Wiki (F4 docking)."""
from __future__ import annotations

import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.setdefault("POSTGRES_SERVER", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5435")


def main() -> int:
    from app.db.session import SessionLocal
    from app.models.knowledge_base import DocumentArtifact
    from app.services.clause_projection import ARTIFACT_TYPE, sync_clause_projection_to_wiki

    db = SessionLocal()
    try:
        arts = (
            db.query(DocumentArtifact)
            .filter(
                DocumentArtifact.artifact_type == ARTIFACT_TYPE,
                DocumentArtifact.status == "active",
            )
            .all()
        )
        n = 0
        for art in arts:
            clauses = (art.metadata_json or {}).get("clauses") or []
            if not clauses:
                continue
            page = sync_clause_projection_to_wiki(
                db=db,
                document_id=art.document_id,
                clauses=clauses,
            )
            print("synced", art.document_id, "clauses=", len(clauses), "page=", getattr(page, "slug", None))
            n += 1
        db.commit()
        print("total_synced", n)
        return 0 if n else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
