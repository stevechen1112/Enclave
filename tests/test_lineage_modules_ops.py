"""Citation lineage, module gating, wiki/graph revoke convergence tests."""
from __future__ import annotations

import os
import uuid
import hashlib
from datetime import datetime, timezone

import pytest

from app.gateway.citation import CitationBuilder
from app.gateway.contracts import ChunkResult
from app.services.product_license import ProductModule, is_module_enabled


class TestCitationLineage:
    def test_enrich_from_document_fields(self, test_engine):
        import app.models  # noqa: F401
        from app.db.base_class import Base
        from sqlalchemy.orm import sessionmaker
        from app.models.document import Document
        from app.models.tenant import Tenant

        Base.metadata.create_all(bind=test_engine)
        Session = sessionmaker(bind=test_engine)
        db = Session()
        try:
            tenant = Tenant(id=uuid.uuid4(), name="CiteTenant", plan="free", status="active")
            db.add(tenant)
            db.flush()
            doc = Document(
                tenant_id=tenant.id,
                filename="policy.pdf",
                file_type="pdf",
                status="completed",
                source_system="nas_smb",
                source_record_id="nas://share/policy.pdf",
                content_hash="sha256:deadbeef",
                version=3,
            )
            db.add(doc)
            db.commit()

            results = [
                ChunkResult(
                    id="chunk-1",
                    content="secret policy",
                    score=0.9,
                    result_type="chunk",
                    document_id=str(doc.id),
                    provider="enclave",
                    provider_version="1.0",
                )
            ]
            citations = CitationBuilder().build(results, acl_revision=2, db=db)
            assert len(citations) == 1
            c = citations[0]
            assert c.canonical_document_id == doc.id
            assert c.source_system == "nas_smb"
            assert c.source_record_id == "nas://share/policy.pdf"
            assert c.content_hash == "sha256:deadbeef"
            assert c.document_revision == 3
            assert c.provider == "enclave"
            assert c.acl_revision == 2

            metrics = CitationBuilder().completeness(citations, object_level=True)
            assert metrics["rate"] == 1.0
            assert metrics["complete"] == 1
        finally:
            db.close()

    def test_completeness_fails_without_canonical_id(self):
        from app.gateway.contracts import Citation

        citations = [
            Citation(
                citation_id="c1",
                canonical_document_id=uuid.UUID(int=0),
                document_revision=1,
                provider="enclave",
                acl_revision=1,
                content_hash="sha256:x",
            )
        ]
        metrics = CitationBuilder().completeness(citations, object_level=True)
        assert metrics["rate"] == 0.0
        assert "canonical_document_id" in metrics["missing"][0]["missing"]

    def test_build_derives_content_hash_from_text(self):
        results = [
            ChunkResult(
                id="c1", content="hello lineage", score=1.0, result_type="chunk",
                document_id=str(uuid.uuid4()), provider="enclave",
            )
        ]
        cites = CitationBuilder().build(results, acl_revision=1)
        assert cites[0].content_hash
        assert CitationBuilder().completeness(cites)["rate"] == 1.0

    def test_opaque_document_revision_is_deterministic(self):
        """Opaque connector revisions must survive process restarts unchanged."""
        opaque_revision = "sharepoint-etag:W/\"7f2c-2026-08-25\""
        expected = (
            int.from_bytes(hashlib.sha256(opaque_revision.encode("utf-8")).digest()[:4], "big")
            % 2_000_000_000
        ) + 1

        assert CitationBuilder._coerce_revision(opaque_revision) == expected
        assert CitationBuilder._coerce_revision(opaque_revision) == expected


class TestModuleGating:
    def test_packs_disabled_core_adapters_remain(self, monkeypatch):
        monkeypatch.delenv("RAGFLOW_ENABLED", raising=False)
        monkeypatch.delenv("PIPESHUB_ENABLED", raising=False)
        monkeypatch.delenv("WEKNORA_ENABLED", raising=False)

        assert is_module_enabled(ProductModule.BASE) is True
        assert is_module_enabled(ProductModule.DOCUMENT_INTELLIGENCE) is False
        assert is_module_enabled(ProductModule.ENTERPRISE_CONNECT) is False
        assert is_module_enabled(ProductModule.KNOWLEDGE_COMPILER) is False

        from app.gateway.adapter_factory import build_gateway_adapters
        adapters = build_gateway_adapters()
        assert "document" in adapters
        assert "connector" not in adapters
        assert "wiki" not in adapters
        assert "graph" not in adapters

    def test_require_module_raises_when_disabled(self, monkeypatch):
        monkeypatch.setenv("WEKNORA_ENABLED", "false")
        from fastapi import HTTPException
        from app.services.module_gate import require_module

        with pytest.raises(HTTPException) as ei:
            require_module(ProductModule.KNOWLEDGE_COMPILER)
        assert ei.value.status_code == 403
        assert ei.value.detail["error"] == "module_disabled"

    def test_wiki_compile_marks_failed_when_disabled(self, test_engine, monkeypatch):
        monkeypatch.setenv("WEKNORA_ENABLED", "false")
        import app.models  # noqa: F401
        from app.db.base_class import Base
        from sqlalchemy.orm import sessionmaker
        from app.models.tenant import Tenant
        from app.models.knowledge_base import KnowledgeBase
        from app.services.wiki_compiler import WikiCompiler

        Base.metadata.create_all(bind=test_engine)
        Session = sessionmaker(bind=test_engine)
        db = Session()
        try:
            tenant = Tenant(id=uuid.uuid4(), name="WikiOff", plan="free", status="active")
            db.add(tenant)
            db.flush()
            kb = KnowledgeBase(id=uuid.uuid4(), tenant_id=tenant.id, name="kb-off", status="active")
            db.add(kb)
            db.commit()
            page = WikiCompiler().compile_kb(
                db, tenant_id=tenant.id, kb_id=kb.id, page_type="summary",
            )
            assert page.status == "failed"
        finally:
            db.close()


class TestWikiGraphRevoke:
    def test_wiki_tombstone_and_stale_recompile_path(self, test_engine, monkeypatch):
        monkeypatch.setenv("WEKNORA_ENABLED", "false")
        import app.models  # noqa: F401
        from app.db.base_class import Base
        from sqlalchemy.orm import sessionmaker
        from app.models.tenant import Tenant
        from app.models.knowledge_base import KnowledgeBase
        from app.models.wiki import WikiPage
        from app.services.wiki_compiler import WikiCompiler

        Base.metadata.create_all(bind=test_engine)
        Session = sessionmaker(bind=test_engine)
        db = Session()
        try:
            tenant = Tenant(id=uuid.uuid4(), name="WikiRevoke", plan="free", status="active")
            db.add(tenant)
            db.flush()
            kb_row = KnowledgeBase(id=uuid.uuid4(), tenant_id=tenant.id, name="kb-revoke", status="active")
            db.add(kb_row)
            db.flush()
            doc_a = str(uuid.uuid4())
            doc_b = str(uuid.uuid4())
            kb = kb_row.id
            only = WikiPage(
                tenant_id=tenant.id, kb_id=kb, slug="only", title="only",
                page_type="summary", status="published",
                source_document_ids=[doc_a], active_revision=1,
            )
            multi = WikiPage(
                tenant_id=tenant.id, kb_id=kb, slug="multi", title="multi",
                page_type="summary", status="published",
                source_document_ids=[doc_a, doc_b], active_revision=1,
            )
            db.add_all([only, multi])
            db.commit()

            result = WikiCompiler().tombstone_by_source_document(
                db, tenant.id, doc_a, recompile=True,
            )
            assert result["tombstoned"] == 1
            assert result["stale"] == 1
            db.refresh(only)
            db.refresh(multi)
            assert only.status == "tombstoned"
            assert only.tombstoned_at is not None
            assert multi.status in ("stale", "failed")  # recompile disabled → failed
            assert doc_a not in [str(x) for x in (multi.source_document_ids or [])]
            assert doc_b in [str(x) for x in (multi.source_document_ids or [])]
        finally:
            db.close()

    def test_graph_tombstone_and_acl_post_check(self, test_engine):
        import app.models  # noqa: F401
        from app.db.base_class import Base
        from sqlalchemy.orm import sessionmaker
        from app.models.tenant import Tenant
        from app.models.document import Document
        from app.core.authorization import AuthorizationContext
        from app.gateway.authorization import get_gateway_authorizer
        from app.services.graph_service import GraphService

        Base.metadata.create_all(bind=test_engine)
        Session = sessionmaker(bind=test_engine)
        db = Session()
        try:
            tenant = Tenant(id=uuid.uuid4(), name="GraphRevoke", plan="free", status="active")
            db.add(tenant)
            db.flush()
            subject = uuid.uuid4()
            doc = Document(
                tenant_id=tenant.id, filename="machine.pdf", file_type="pdf", status="completed",
            )
            db.add(doc)
            db.flush()
            doc_id = doc.id
            svc = GraphService()
            ent = svc.upsert_entity(
                db, tenant_id=tenant.id, name="Machine-A", entity_type="asset",
                source_document_id=doc_id,
            )
            db.commit()

            authz = AuthorizationContext(
                subject_id=subject,
                tenant_id=tenant.id,
                role_ids=[],
                department_ids=[],
                is_superuser=False,
                policy_revision=1,
            )
            # pre: visible
            found = svc.search_entities(db, tenant.id, "Machine", authz)
            assert any(e["id"] == str(ent.id) for e in found)

            # revoke deny + tombstone
            get_gateway_authorizer().add_deny_entry(str(doc_id), subject, tenant_id=tenant.id)
            stats = svc.tombstone_by_source_document(db, tenant.id, doc_id)
            assert stats["entities"] == 1

            # post: hidden by tombstone and deny
            found2 = svc.search_entities(db, tenant.id, "Machine", authz)
            assert found2 == []
            trav = svc.traverse(db, tenant.id, ent.id, authz)
            assert trav["denied"] is True or trav["entities"] == []
        finally:
            db.close()


class TestOpsScriptsImportable:
    def test_ops_lifecycle_file_exists(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        assert (root / "scripts" / "ops_lifecycle.py").is_file()
        assert (root / "scripts" / "preflight_check.py").is_file()
