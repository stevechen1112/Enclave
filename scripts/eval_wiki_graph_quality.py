"""Wiki/Graph quality eval harness (schema + revoke visibility).
Writes artifacts/wiki_graph_eval_last_run.json
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
ARTIFACT = ROOT / "artifacts" / "wiki_graph_eval_last_run.json"


def _live_weknora_check() -> dict:
    """Hit running WeKnora if enabled; never invent PASS."""
    import httpx

    enabled = os.getenv("WEKNORA_ENABLED", "").lower() == "true"
    base = os.getenv("WEKNORA_BASE_URL", "http://localhost:8081").rstrip("/")
    key = os.getenv("WEKNORA_API_KEY", "")
    out = {"enabled": enabled, "base_url": base, "healthy": False, "http_status": None}
    if not enabled:
        out["skipped"] = "WEKNORA_ENABLED not true"
        return out
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        with httpx.Client(timeout=15.0) as client:
            for path in ("/health", "/api/health", "/api/v1/health", "/"):
                resp = client.get(f"{base}{path}", headers=headers)
                out["http_status"] = resp.status_code
                if resp.status_code < 500:
                    out["healthy"] = True
                    out["path"] = path
                    break
    except Exception as exc:
        out["error"] = str(exc)[:300]
    return out


def main() -> int:
    # 尊重 .env；勿強制關閉真實 WeKnora
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

    from app.db.session import SessionLocal
    from app.models.tenant import Tenant
    from app.models.knowledge_base import KnowledgeBase
    from app.models.wiki import WikiPage, WIKI_PAGE_TYPES
    from app.models.document import Document
    from app.services.wiki_compiler import WikiCompiler
    from app.services.graph_service import GraphService
    from app.core.authorization import AuthorizationContext
    from app.gateway.authorization import get_gateway_authorizer

    db = SessionLocal()
    checks = {
        "page_types": len(WIKI_PAGE_TYPES),
        "six_types": len(WIKI_PAGE_TYPES) == 6,
        "weknora_live": _live_weknora_check(),
    }
    try:
        tenant = Tenant(id=uuid.uuid4(), name="WikiEval", plan="free", status="active")
        db.add(tenant)
        db.flush()
        kb = KnowledgeBase(id=uuid.uuid4(), tenant_id=tenant.id, name="eval", status="active")
        db.add(kb)
        db.flush()
        doc = Document(tenant_id=tenant.id, filename="a.pdf", file_type="pdf", status="completed")
        db.add(doc)
        db.flush()

        # WeKnora off → compile failed (no placeholder publish)
        page = WikiCompiler().compile_kb(db, tenant.id, kb.id, "summary", [str(doc.id)])
        checks["no_placeholder_publish"] = page.status == "failed"

        published = WikiPage(
            tenant_id=tenant.id, kb_id=kb.id, slug="pub", title="pub",
            page_type="summary", status="published",
            source_document_ids=[str(doc.id)], active_revision=1,
        )
        db.add(published)
        db.commit()
        stats = WikiCompiler().tombstone_by_source_document(db, tenant.id, str(doc.id), recompile=False)
        checks["revoke_tombstone"] = stats["tombstoned"] >= 1

        svc = GraphService()
        ent = svc.upsert_entity(
            db, tenant_id=tenant.id, name="Entity-X", entity_type="thing",
            source_document_id=doc.id,
        )
        db.commit()
        subject = uuid.uuid4()
        authz = AuthorizationContext(
            tenant_id=tenant.id, subject_id=subject, role_ids=[], policy_revision=1,
        )
        before = svc.search_entities(db, tenant.id, "Entity", authz)
        get_gateway_authorizer().add_deny_entry(str(doc.id), subject, tenant_id=tenant.id)
        svc.tombstone_by_source_document(db, tenant.id, doc.id)
        after = svc.search_entities(db, tenant.id, "Entity", authz)
        checks["graph_visible_before"] = any(e["id"] == str(ent.id) for e in before)
        checks["graph_hidden_after_revoke"] = len(after) == 0
        checks["passed"] = all([
            checks["six_types"],
            checks["no_placeholder_publish"],
            checks["revoke_tombstone"],
            checks["graph_visible_before"],
            checks["graph_hidden_after_revoke"],
        ])
    except Exception as exc:
        checks["passed"] = False
        checks["error"] = str(exc)[:500]
    finally:
        db.close()

    live = checks.get("weknora_live") or {}
    # 本地 schema/revoke 必須過；若啟用 WeKnora 則健康檢查也必須過
    local_ok = bool(checks.get("passed"))
    live_ok = (not live.get("enabled")) or bool(live.get("healthy"))
    status = "PASS" if (local_ok and live_ok) else "FAIL"
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "checks": checks,
        "note": "Local revoke/schema + optional live WeKnora health; production corpus quality still expandable",
    }
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
