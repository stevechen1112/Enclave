"""Tests for connector sync helpers and content reference."""
import uuid
import pytest
from sqlalchemy.orm import sessionmaker

from app.services.content_reference import build_content_reference, resolve_content_bytes
from app.services.external_principal import ExternalPrincipalService
from app.services.graph_service import GraphService
from app.models.tenant import Tenant
from app.core.authorization import AuthorizationContext


class TestContentReference:
    def test_file_reference_roundtrip(self, tmp_path):
        f = tmp_path / "doc.txt"
        f.write_text("hello content", encoding="utf-8")
        tenant_id = uuid.uuid4()
        doc_id = uuid.uuid4()
        ref, meta = build_content_reference(str(f), tenant_id, doc_id)
        data = resolve_content_bytes(ref, meta)
        assert data == b"hello content"


class TestConnectorDomainServices:
    def test_external_principal_and_graph(self, test_engine):
        import app.models  # noqa: F401
        from app.db.base_class import Base
        Base.metadata.create_all(bind=test_engine)

        Session = sessionmaker(bind=test_engine)
        db = Session()
        try:
            tenant = Tenant(id=uuid.uuid4(), name="GraphTest", plan="free", status="active")
            db.add(tenant)
            db.flush()

            principal_svc = ExternalPrincipalService()
            subject_id = uuid.uuid4()
            principal_svc.map_principal(
                db, tenant.id, "sharepoint", "ext-user-1", "user",
                mapped_subject_id=subject_id, mapped_subject_type="user",
            )
            count = principal_svc.apply_acl_entries(
                db,
                tenant.id,
                [{
                    "provider": "sharepoint",
                    "principal_external_id": "ext-user-1",
                    "source_record_id": "sp-file-001",
                    "effect": "allow",
                }],
            )
            assert count == 1

            graph_svc = GraphService()
            e1 = graph_svc.upsert_entity(db, tenant.id, "Entity A", "concept")
            e2 = graph_svc.upsert_entity(db, tenant.id, "Entity B", "concept")
            graph_svc.upsert_edge(db, tenant.id, e1.id, e2.id, "relates_to")
            db.commit()

            authz = AuthorizationContext(
                tenant_id=tenant.id,
                subject_id=subject_id,
                is_superuser=True,
            )
            result = graph_svc.traverse(db, tenant.id, e1.id, authz, depth=1)
            assert result["denied"] is False
            assert len(result["entities"]) >= 1
        finally:
            db.close()
