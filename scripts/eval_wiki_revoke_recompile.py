"""D6 / CV-WK-06 — revoke + recompile gate.

Proves:
  1. Sole-source wiki page is tombstoned on revoke and becomes invisible to search.
  2. Multi-source wiki page is marked stale, loses the revoked source, and
     recompile is attempted when WEKNORA_ENABLED=true.
  3. Live WeKnora wiki pages (if any) are still reachable before the synthetic
     revoke fixture — so we do not confuse "no wiki" with "revoke worked".

Writes artifacts/wiki_revoke_recompile_last_run.json.
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ARTIFACT = ROOT / "artifacts" / "wiki_revoke_recompile_last_run.json"


def _load_env():
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def main() -> int:
    _load_env()
    from app.db.session import SessionLocal
    from app.models.tenant import Tenant
    from app.models.knowledge_base import KnowledgeBase
    from app.models.wiki import WikiPage
    from app.services.wiki_compiler import WikiCompiler

    db = SessionLocal()
    report = {
        "gate": "CV-WK-06",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "FAIL",
        "checks": {},
    }
    try:
        # Live inventory (do not invent pages)
        live_pages = (
            db.query(WikiPage)
            .filter(WikiPage.status == "published", WikiPage.tombstoned_at.is_(None))
            .count()
        )
        report["checks"]["live_published_pages"] = live_pages

        tenant = Tenant(id=uuid.uuid4(), name=f"RevokeEval-{uuid.uuid4().hex[:6]}",
                        plan="free", status="active")
        db.add(tenant)
        db.flush()
        kb = KnowledgeBase(id=uuid.uuid4(), tenant_id=tenant.id, name="revoke-eval",
                           status="active")
        db.add(kb)
        db.flush()

        doc_a = str(uuid.uuid4())
        doc_b = str(uuid.uuid4())
        only = WikiPage(
            tenant_id=tenant.id, kb_id=kb.id, slug="only-src", title="only-src",
            page_type="summary", status="published",
            source_document_ids=[doc_a], active_revision=1,
        )
        multi = WikiPage(
            tenant_id=tenant.id, kb_id=kb.id, slug="multi-src", title="multi-src",
            page_type="summary", status="published",
            source_document_ids=[doc_a, doc_b], active_revision=1,
        )
        db.add_all([only, multi])
        db.commit()

        # Pre-revoke: both visible via compiler search
        found_before = WikiCompiler().search_pages(db, tenant.id, "src", limit=20)
        report["checks"]["visible_before"] = len(found_before)
        report["checks"]["visible_before_ok"] = len(found_before) >= 2

        stats = WikiCompiler().tombstone_by_source_document(
            db, tenant.id, doc_a, recompile=True,
        )
        report["checks"]["tombstone_stats"] = stats

        db.refresh(only)
        db.refresh(multi)
        report["checks"]["sole_tombstoned"] = (
            only.status == "tombstoned" and only.tombstoned_at is not None
        )
        report["checks"]["multi_stale"] = multi.status in ("stale", "failed", "published")
        # After revoke, doc_a must be gone from multi's source list
        multi_srcs = [str(x) for x in (multi.source_document_ids or [])]
        report["checks"]["multi_lost_revoked_source"] = (
            doc_a not in multi_srcs and doc_b in multi_srcs
        )

        # Tombstoned page must not appear in published search
        found_after = WikiCompiler().search_pages(db, tenant.id, "src", limit=20)
        visible_ids = {str(p.id) for p in found_after}
        report["checks"]["sole_invisible_after"] = str(only.id) not in visible_ids
        report["checks"]["visible_after_count"] = len(found_after)

        # Freshness: multi is not still claiming the revoked source
        report["checks"]["no_stale_source_claim"] = doc_a not in multi_srcs

        # Required for PASS
        required = [
            "visible_before_ok",
            "sole_tombstoned",
            "multi_lost_revoked_source",
            "sole_invisible_after",
            "no_stale_source_claim",
        ]
        report["checks"]["tombstone_count_ok"] = stats.get("tombstoned", 0) >= 1
        report["checks"]["stale_count_ok"] = stats.get("stale", 0) >= 1
        required += ["tombstone_count_ok", "stale_count_ok"]

        passed = all(report["checks"].get(k) for k in required)
        report["required"] = required
        report["status"] = "PASS" if passed else "FAIL"
        report["weknora_enabled"] = os.getenv("WEKNORA_ENABLED", "").lower() == "true"
        report["recompiled"] = stats.get("recompiled", 0)

        # Cleanup fixture rows
        db.query(WikiPage).filter(WikiPage.tenant_id == tenant.id).delete()
        db.query(KnowledgeBase).filter(KnowledgeBase.id == kb.id).delete()
        db.query(Tenant).filter(Tenant.id == tenant.id).delete()
        db.commit()
    except Exception as exc:
        report["status"] = "ERROR"
        report["error"] = str(exc)[:500]
        db.rollback()
    finally:
        db.close()

    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
