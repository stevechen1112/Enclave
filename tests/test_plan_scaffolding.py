"""Integration tests for plan Phase 2-7 scaffolding."""
import uuid
import pytest
from app.services.parse_router import classify_document, ParseRoute
from app.services.product_license import ProductModule, is_module_enabled
from app.models.wiki import WIKI_PAGE_TYPES


class TestParseRouter:
    def test_csv_native_structured(self, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text("a,b\n1,2")
        route = classify_document(str(f), "csv")
        assert route == ParseRoute.NATIVE_STRUCTURED

    def test_pdf_route(self, tmp_path):
        f = tmp_path / "doc.pdf"
        f.write_bytes(b"%PDF-1.4 minimal")
        route = classify_document(str(f), "pdf")
        assert route in (ParseRoute.NATIVE_FAST, ParseRoute.RAGFLOW_DEEPDOC)


class TestProductLicense:
    def test_base_always_enabled(self):
        assert is_module_enabled(ProductModule.BASE)

    def test_modules_status(self):
        from app.services.product_license import module_status
        status = module_status()
        assert "enclave_base" in status
        assert status["enclave_base"] is True


class TestWikiTypes:
    def test_six_page_types(self):
        assert len(WIKI_PAGE_TYPES) == 6
        assert "summary" in WIKI_PAGE_TYPES
        assert "comparison" in WIKI_PAGE_TYPES


class TestParentChunkHierarchy:
    def test_parent_child_relationship(self, test_engine):
        import app.models  # noqa: F401
        from app.db.base_class import Base
        from sqlalchemy.orm import sessionmaker
        from app.models.document import Document, DocumentChunk
        from app.models.tenant import Tenant

        Base.metadata.create_all(bind=test_engine)
        Session = sessionmaker(bind=test_engine)
        db = Session()
        try:
            tenant = Tenant(id=uuid.uuid4(), name="ChunkHierarchy", plan="free", status="active")
            db.add(tenant)
            db.flush()
            doc = Document(
                tenant_id=tenant.id,
                filename="parent.pdf",
                file_type="pdf",
                status="completed",
            )
            db.add(doc)
            db.flush()
            parent = DocumentChunk(
                tenant_id=tenant.id,
                document_id=doc.id,
                chunk_index=0,
                text="parent section",
                chunk_hash="p1",
            )
            db.add(parent)
            db.flush()
            child = DocumentChunk(
                tenant_id=tenant.id,
                document_id=doc.id,
                chunk_index=1,
                text="child detail",
                chunk_hash="c1",
                parent_chunk_id=parent.id,
            )
            db.add(child)
            db.commit()
            db.refresh(parent)
            assert len(parent.child_chunks) == 1
            assert parent.child_chunks[0].text == "child detail"
            assert child.parent_chunk.id == parent.id
        finally:
            db.close()


class TestSandbox:
    def test_rejects_unknown_image(self):
        from app.services.sandbox import AgentSandbox
        sb = AgentSandbox()
        result = sb.run("ubuntu:latest", ["echo", "hi"])
        assert result.success is False

    def test_network_without_proxy_fail_closed(self):
        from app.services.sandbox import AgentSandbox
        sb = AgentSandbox(network_disabled=False)
        result = sb.run("alpine:3.19", ["echo", "hi"])
        assert result.success is False
        assert "EGRESS_PROXY" in (result.error or "")

    def test_allowed_image_echo_ok(self):
        from app.services.sandbox import AgentSandbox
        sb = AgentSandbox(timeout_seconds=20)
        result = sb.run("alpine:3.19", ["echo", "ok"])
        # Docker may be unavailable in CI — accept either success or docker-missing
        if result.error and "docker not available" in result.error:
            pytest.skip("docker not available")
        assert result.success is True
        assert "ok" in result.output
