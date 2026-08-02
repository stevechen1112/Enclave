"""Online citation lineage sampling — writes artifacts/lineage_online_last_run.json."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ARTIFACT = ROOT / "artifacts" / "lineage_online_last_run.json"


def main() -> int:
    from sqlalchemy.orm import sessionmaker
    from app.db.session import SessionLocal
    from app.models.document import Document, DocumentChunk
    from app.gateway.citation import CitationBuilder
    from app.gateway.contracts import ChunkResult

    limit = int(os.getenv("LINEAGE_SAMPLE_SIZE", "50"))
    db = SessionLocal()
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "FAIL",
        "sample_size": 0,
        "completeness": {},
    }
    try:
        chunks = (
            db.query(DocumentChunk)
            .join(Document, Document.id == DocumentChunk.document_id)
            .filter(Document.tombstoned_at.is_(None))
            .order_by(DocumentChunk.created_at.desc())
            .limit(limit)
            .all()
        )
        results = []
        for ch in chunks:
            meta = dict(ch.metadata_json or {})
            results.append(
                ChunkResult(
                    id=str(ch.id),
                    content=(ch.text or "")[:200],
                    score=1.0,
                    result_type="chunk",
                    document_id=str(ch.document_id),
                    provider="enclave",
                    provider_version="1.0",
                    metadata=meta,
                )
            )
        citations = CitationBuilder().build(results, acl_revision=1, db=db)
        metrics = CitationBuilder().completeness(citations, object_level=True)
        payload["sample_size"] = len(citations)
        payload["completeness"] = metrics
        # Empty corpus is not evidence of lineage completeness
        if metrics["total"] == 0:
            payload["status"] = "FAIL"
            payload["note"] = "no_indexed_chunks_to_sample"
        elif metrics["rate"] >= 1.0:
            payload["status"] = "PASS"
        else:
            payload["status"] = "FAIL"
            payload["missing"] = metrics.get("missing", [])[:20]
    except Exception as exc:
        payload["status"] = "ERROR"
        payload["error"] = str(exc)[:500]
    finally:
        db.close()

    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
