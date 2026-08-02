"""Seed a real Wiki page into Enclave DB from the live WeKnora wiki KB.

Creates an Enclave KnowledgeBase row whose id matches WEKNORA_KB_ID (the
compiler passes kb_id straight to WeKnora), then runs WikiCompiler.compile_kb
under the Demo Tenant so /knowledge/wiki has real content.
"""
from __future__ import annotations

import os
import pathlib
import sys
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from app.db.session import SessionLocal  # noqa: E402
from app.models.document import Document  # noqa: E402
from app.models.knowledge_base import KnowledgeBase  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.services.wiki_compiler import WikiCompiler  # noqa: E402

WEKNORA_KB_ID = uuid.UUID(os.environ["WEKNORA_KB_ID"])


def main() -> int:
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(Tenant.name == "Demo Tenant").first()
        if not tenant:
            print("Demo Tenant not found")
            return 1
        kb = db.get(KnowledgeBase, WEKNORA_KB_ID)
        if not kb:
            kb = KnowledgeBase(
                id=WEKNORA_KB_ID, tenant_id=tenant.id,
                name="WeKnora Wiki KB", status="active",
            )
            db.add(kb)
            db.flush()
            print("created KB row:", kb.id)
        docs = [
            str(d.id) for d in
            db.query(Document).filter(
                Document.tenant_id == tenant.id,
                Document.status == "completed",
                Document.tombstoned_at.is_(None),
            ).limit(9).all()
        ]
        print("source docs:", len(docs))
        page = WikiCompiler().compile_kb(
            db, tenant_id=tenant.id, kb_id=kb.id,
            page_type="summary", source_document_ids=docs,
        )
        print("page:", page.id, page.slug, page.status, "rev", page.active_revision)
        return 0 if page.status == "published" else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
