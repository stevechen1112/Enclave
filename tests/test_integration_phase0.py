"""
Phase 0-1 Integration Test — End-to-end ACL + Retrieval + Answer

驗證完整流程：
  1. ACL 部門過濾
  2. Gateway 路由與聚合
  3. 快取隔離（不同使用者不共用快取）
  4. Tombstone 刪除後不可搜尋
"""
import uuid
import pytest
from datetime import datetime, timezone

from app.db.session import SessionLocal
from app.models.tenant import Tenant
from app.models.document import Document, DocumentChunk
from app.models.knowledge_base import KnowledgeBase
from app.core.authorization import AuthorizationContext


def _make_authz(tenant_id, user_id, role="employee", dept_ids=None, is_superuser=False):
    return AuthorizationContext(
        tenant_id=tenant_id,
        subject_id=user_id,
        role_ids=[role],
        department_ids=dept_ids or [],
        is_superuser=is_superuser,
        policy_revision=1,
    )


class TestACLIntegration:
    """端到端 ACL 整合測試。"""

    def test_authz_department_inheritance(self):
        dept_a, dept_b = uuid.uuid4(), uuid.uuid4()
        authz = AuthorizationContext(
            tenant_id=uuid.uuid4(), subject_id=uuid.uuid4(),
            role_ids=["employee"], department_ids=[dept_b, dept_a], policy_revision=1,
        )
        assert dept_a in authz.department_ids

    def test_admin_can_access_all(self):
        tid = uuid.uuid4()
        authz = _make_authz(tid, uuid.uuid4(), is_superuser=True)
        assert authz.can_access_document(tid, uuid.uuid4()) is True

    def test_employee_cannot_access_other_department(self):
        tid = uuid.uuid4()
        authz = _make_authz(tid, uuid.uuid4(), dept_ids=[uuid.uuid4()])
        assert authz.can_access_document(tid, uuid.uuid4()) is False

    def test_different_tenant_blocked(self):
        authz = _make_authz(uuid.uuid4(), uuid.uuid4())
        assert authz.can_access_document(uuid.uuid4(), None) is False

    def test_different_users_have_different_fingerprints(self):
        a1 = _make_authz(uuid.uuid4(), uuid.uuid4(), role="employee")
        a2 = _make_authz(uuid.uuid4(), uuid.uuid4(), role="admin")
        assert a1.policy_fingerprint != a2.policy_fingerprint

    def test_policy_revision_changes_fingerprint(self):
        tid, uid = uuid.uuid4(), uuid.uuid4()
        a1 = AuthorizationContext(tenant_id=tid, subject_id=uid, role_ids=["employee"], policy_revision=1)
        a2 = AuthorizationContext(tenant_id=tid, subject_id=uid, role_ids=["employee"], policy_revision=2)
        assert a1.policy_fingerprint != a2.policy_fingerprint


class TestGatewayIntegration:
    """Gateway 整合測試。"""

    def test_gateway_router_initialization(self):
        from app.gateway.router import GatewayRouter
        from app.gateway.adapters.base import MockAdapter
        router = GatewayRouter()
        router.register_adapter("document", MockAdapter(domain="document"))
        assert "document" in router._adapters

    @pytest.mark.asyncio
    async def test_gateway_search_with_authz(self):
        from app.gateway.router import GatewayRouter
        from app.gateway.adapters.base import MockAdapter
        from app.gateway.contracts import SearchDomain
        router = GatewayRouter()
        router.register_adapter("document", MockAdapter(domain="document"))
        authz = _make_authz(uuid.uuid4(), uuid.uuid4(), role="admin", is_superuser=True)
        response = await router.search(authz=authz, query="test", domain=SearchDomain.DOCUMENT)
        assert response.status in ("success", "partial")

    @pytest.mark.asyncio
    async def test_gateway_unauthorized_blocked(self):
        from app.gateway.router import GatewayRouter
        from app.gateway.adapters.base import MockAdapter
        router = GatewayRouter()
        router.register_adapter("document", MockAdapter())
        authz = AuthorizationContext(tenant_id=None, subject_id=uuid.uuid4(), policy_revision=1)  # type: ignore
        response = await router.search(authz=authz, query="test")
        assert response.status == "error"

    @pytest.mark.asyncio
    async def test_gateway_hybrid_multi_adapter(self):
        from app.gateway.router import GatewayRouter
        from app.gateway.adapters.base import MockAdapter
        from app.gateway.contracts import SearchDomain
        router = GatewayRouter()
        router.register_adapter("document", MockAdapter(domain="document"))
        router.register_adapter("wiki", MockAdapter(domain="wiki"))
        authz = _make_authz(uuid.uuid4(), uuid.uuid4(), role="admin", is_superuser=True)
        response = await router.search(authz=authz, query="test", domain=SearchDomain.HYBRID)
        assert response.status == "success"
        assert len(response.audit_trail.providers_called) == 2


class TestCacheIsolation:
    """快取隔離測試。"""

    def test_cache_key_differs_by_user(self):
        from app.services.kb_retrieval import KnowledgeBaseRetriever
        retriever = KnowledgeBaseRetriever()
        tid = uuid.uuid4()
        authz_a = _make_authz(tid, uuid.uuid4(), role="employee")
        authz_b = _make_authz(tid, uuid.uuid4(), role="admin")
        assert retriever._cache_key(tid, "test", "hybrid", 5, 0.0, authz_a) != \
               retriever._cache_key(tid, "test", "hybrid", 5, 0.0, authz_b)

    def test_cache_key_differs_by_policy_revision(self):
        from app.services.kb_retrieval import KnowledgeBaseRetriever
        retriever = KnowledgeBaseRetriever()
        tid, uid = uuid.uuid4(), uuid.uuid4()
        a1 = AuthorizationContext(tenant_id=tid, subject_id=uid, role_ids=["employee"], policy_revision=1)
        a2 = AuthorizationContext(tenant_id=tid, subject_id=uid, role_ids=["employee"], policy_revision=2)
        assert retriever._cache_key(tid, "test", "hybrid", 5, 0.0, a1) != \
               retriever._cache_key(tid, "test", "hybrid", 5, 0.0, a2)

    def test_cache_key_same_user_same_params(self):
        from app.services.kb_retrieval import KnowledgeBaseRetriever
        retriever = KnowledgeBaseRetriever()
        tid, uid = uuid.uuid4(), uuid.uuid4()
        authz = AuthorizationContext(tenant_id=tid, subject_id=uid, role_ids=["employee"], policy_revision=1)
        assert retriever._cache_key(tid, "test", "hybrid", 5, 0.0, authz) == \
               retriever._cache_key(tid, "test", "hybrid", 5, 0.0, authz)


class TestTombstoneIntegration:
    """Tombstone 整合測試。"""

    def test_tombstoned_document_excluded(self, test_engine):
        import app.models  # noqa: F401
        from app.db.base_class import Base
        from sqlalchemy.orm import sessionmaker

        Base.metadata.create_all(bind=test_engine)
        Session = sessionmaker(bind=test_engine)
        db = Session()
        try:
            tid, kid, did = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
            db.add_all([
                Tenant(id=tid, name="Tombstone Test", status="active"),
                KnowledgeBase(id=kid, tenant_id=tid, name="Test KB"),
            ])
            db.flush()
            doc = Document(id=did, tenant_id=tid, knowledge_base_id=kid, filename="s.pdf", file_type="pdf", status="completed", content_hash="abc")
            db.add(doc)
            db.flush()
            db.add(DocumentChunk(id=uuid.uuid4(), tenant_id=tid, document_id=did, chunk_index=0, text="secret", chunk_hash="abc"))
            db.commit()

            assert db.query(Document).filter(Document.tenant_id == tid, Document.tombstoned_at.is_(None)).count() == 1

            doc.tombstoned_at = datetime.now(timezone.utc)
            db.commit()

            assert db.query(Document).filter(Document.tenant_id == tid, Document.tombstoned_at.is_(None)).count() == 0
        finally:
            db.rollback()
            db.close()
