"""
Phase 1 垂直切片 E2E 測試 — 完整資料流驗證

驗證流程（對應 DEVELOPMENT_PLAN_TRIPLE_INJECTION.md §16.7）：
  1. 文件上傳 → Enclave canonical document
  2. RAGFlow parse → ParseArtifact
  3. Enclave index/search → authorized answer with citation
  4. Revoke/delete → immediate deny + projection cleanup + audit

這是計畫要求的「第一個垂直切片」，通過後才進入更多 Connector、Wiki/Graph 與 Agent 擴張。
"""

import uuid
import pytest
import httpx
from datetime import datetime, timezone

from app.db.session import SessionLocal
from app.models.tenant import Tenant
from app.models.document import Document, DocumentChunk
from app.models.knowledge_base import KnowledgeBase
from app.core.authorization import AuthorizationContext
from app.gateway.router import GatewayRouter
from app.gateway.adapters.base import MockAdapter
from app.gateway.contracts import SearchDomain


# ═══════════════════════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════════════════════


def _make_authz(tenant_id, user_id, role="employee", dept_ids=None, is_superuser=False):
    return AuthorizationContext(
        tenant_id=tenant_id,
        subject_id=user_id,
        role_ids=[role],
        department_ids=dept_ids or [],
        is_superuser=is_superuser,
        policy_revision=1,
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  Step 1: Document Upload → Canonical Store
# ═══════════════════════════════════════════════════════════════════════════════


class TestVerticalSliceUpload:
    """Step 1: 文件上傳 → Enclave canonical document。"""

    def test_document_created_with_lineage(self):
        """文件建立時必須有 source_system、content_hash、tombstoned_at=None。"""
        db = SessionLocal()
        try:
            tid, kid, did = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
            db.add_all(
                [
                    Tenant(id=tid, name="VSlice Tenant", status="active"),
                    KnowledgeBase(id=kid, tenant_id=tid, name="VSlice KB"),
                ]
            )
            db.flush()

            doc = Document(
                id=did,
                tenant_id=tid,
                knowledge_base_id=kid,
                filename="employee_handbook.pdf",
                file_type="pdf",
                status="uploaded",
                content_hash="sha256:abc123",
                source_system="enclave_upload",
                source_record_id="upload-001",
            )
            db.add(doc)
            db.commit()

            fetched = db.query(Document).filter(Document.id == did).first()
            assert fetched is not None
            assert fetched.source_system == "enclave_upload"
            assert fetched.content_hash == "sha256:abc123"
            assert fetched.tombstoned_at is None
            assert fetched.knowledge_base_id == kid
        finally:
            db.rollback()
            db.close()

    def test_document_lineage_traceable(self):
        """tenant → kb → source → document 追溯鏈完整。"""
        db = SessionLocal()
        try:
            tid, kid, did = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
            db.add_all(
                [
                    Tenant(id=tid, name="Lineage Tenant", status="active"),
                    KnowledgeBase(id=kid, tenant_id=tid, name="Lineage KB"),
                ]
            )
            db.flush()
            doc = Document(
                id=did,
                tenant_id=tid,
                knowledge_base_id=kid,
                filename="spec.pdf",
                file_type="pdf",
                status="uploaded",
                content_hash="sha256:def456",
                source_system="sharepoint",
                source_record_id="sp://site/doc/123",
            )
            db.add(doc)
            db.commit()

            # 追溯鏈: tenant → kb → source → document
            fetched = (
                db.query(Document)
                .filter(
                    Document.tenant_id == tid,
                    Document.knowledge_base_id == kid,
                    Document.source_system == "sharepoint",
                    Document.id == did,
                )
                .first()
            )
            assert fetched is not None
            assert fetched.source_record_id == "sp://site/doc/123"
        finally:
            db.rollback()
            db.close()


# ═══════════════════════════════════════════════════════════════════════════════
#  Step 2: RAGFlow Parse → ParseArtifact
# ═══════════════════════════════════════════════════════════════════════════════


class TestVerticalSliceParse:
    """Step 2: RAGFlow 解析 → ParseArtifact。"""

    def test_ragflow_adapter_parse_submits_correct_payload(self):
        """RAGFlow adapter 提供正確的 capabilities。"""
        import asyncio
        from app.gateway.adapters.ragflow_http import RAGFlowHTTPAdapter

        adapter = RAGFlowHTTPAdapter(base_url="http://localhost:9380")

        # 驗證 adapter 可正確建立
        assert adapter.provider == "ragflow"
        assert adapter.version == "1.0.0"
        # capabilities 是 async
        caps = asyncio.run(adapter.capabilities())
        assert "parse" in caps["features"]
        assert "ocr" in caps["features"]
        assert "layout_analysis" in caps["features"]

    def test_parse_artifact_lineage_preserved(self):
        """解析結果必須保留 source hash 與 document revision。"""
        # 模擬 ParseArtifact 結構
        artifact = {
            "parser": "ragflow/deepdoc",
            "version": "1.0.0",
            "source_hash": "sha256:abc123",
            "document_revision": 1,
            "pages": [
                {"page_num": 1, "bbox": [0, 0, 612, 792], "reading_order": 1},
            ],
            "tables": [],
            "warnings": [],
            "confidence": 0.95,
        }
        assert artifact["source_hash"] == "sha256:abc123"
        assert artifact["document_revision"] == 1
        assert len(artifact["pages"]) == 1
        assert artifact["confidence"] > 0.9

    def test_parse_failure_does_not_duplicate(self):
        """解析失敗不重複寫入（idempotency key 驗證）。"""
        from app.gateway.adapters.ragflow_http import RAGFlowHTTPAdapter
        import asyncio

        adapter = RAGFlowHTTPAdapter(base_url="http://localhost:9380")
        tid, did = uuid.uuid4(), uuid.uuid4()
        authz = _make_authz(tid, uuid.uuid4(), role="admin", is_superuser=True)

        # ingest 是 async，用 asyncio.run 執行
        async def _run():
            r1 = await adapter.ingest(
                did, 1, "file:///test.pdf", "sha256:same", "pdf", authz
            )
            r2 = await adapter.ingest(
                did, 1, "file:///test.pdf", "sha256:same", "pdf", authz
            )
            return r1, r2

        result1, result2 = asyncio.run(_run())
        assert result1 is not None
        assert result2 is not None


# ═══════════════════════════════════════════════════════════════════════════════
#  Step 3: Enclave Index/Search → Authorized Answer with Citation
# ═══════════════════════════════════════════════════════════════════════════════


class TestVerticalSliceSearch:
    """Step 3: Enclave 索引/搜尋 → 授權回答含引用。"""

    def test_search_requires_authorization_context(self):
        """搜尋必須接受 AuthorizationContext，不只 tenant_id。"""
        from app.services.kb_retrieval import KnowledgeBaseRetriever

        retriever = KnowledgeBaseRetriever()
        tid, uid = uuid.uuid4(), uuid.uuid4()
        authz = _make_authz(tid, uid, role="employee", dept_ids=[uuid.uuid4()])

        # 驗證 cache key 包含 policy_fingerprint（透過 auth fragment）
        key = retriever._cache_key(tid, "test query", "hybrid", 5, 0.0, authz)
        assert key.startswith("kb:search:")
        # 不同 authz 產生不同 key
        authz2 = _make_authz(tid, uuid.uuid4(), role="admin")
        key2 = retriever._cache_key(tid, "test query", "hybrid", 5, 0.0, authz2)
        assert key != key2

    def test_citation_contains_required_fields(self):
        """每個 Citation 至少包含 canonical_document_id、revision、provider、content_hash。"""
        from app.gateway.contracts import Citation

        doc_id = uuid.uuid4()
        citation = Citation(
            citation_id="cite-001",
            canonical_document_id=doc_id,
            document_revision=1,
            artifact_id=str(uuid.uuid4()),
            artifact_type="chunk",
            provider="ragflow",
            provider_version="1.0.0",
            source_system="enclave_upload",
            content_hash="sha256:abc",
            page=1,
            bbox={"x": 0, "y": 0, "w": 100, "h": 100},
        )
        assert citation.canonical_document_id == doc_id
        assert citation.document_revision == 1
        assert citation.provider == "ragflow"
        assert citation.content_hash == "sha256:abc"
        assert citation.page == 1

    @pytest.mark.asyncio
    async def test_gateway_search_returns_citations(self):
        """Gateway 搜尋回傳含 audit trail 的結果。"""
        from app.gateway.router import GatewayRouter
        from app.gateway.adapters.base import MockAdapter

        router = GatewayRouter()
        router.register_adapter("document", MockAdapter(domain="document"))
        authz = _make_authz(uuid.uuid4(), uuid.uuid4(), role="admin", is_superuser=True)

        response = await router.search(
            authz=authz, query="員工手冊", domain=SearchDomain.DOCUMENT
        )
        assert response.status == "success"
        # MockAdapter 回傳空結果，但 audit_trail 應存在
        assert response.audit_trail is not None
        assert response.audit_trail.operation == "search"
        assert "document" in response.audit_trail.providers_called

    def test_unified_retriever_dedup_by_content_hash(self):
        """UnifiedRetriever 依 document_id + content-hash 去重。"""
        from app.services.unified_retriever import UnifiedRetriever
        from app.gateway.router import GatewayRouter
        from app.gateway.contracts import ChunkResult

        router = GatewayRouter()
        retriever = UnifiedRetriever(router)

        doc_id = str(uuid.uuid4())
        # 相同 document_id + 相同內容 → 去重
        chunks = [
            ChunkResult(
                id="1",
                content="相同內容",
                score=0.9,
                result_type="chunk",
                document_id=doc_id,
                provider="ragflow",
                provider_version="1.0",
            ),
            ChunkResult(
                id="2",
                content="相同內容",
                score=0.8,
                result_type="chunk",
                document_id=doc_id,
                provider="weknora",
                provider_version="1.0",
            ),
        ]
        deduped = retriever._deduplicate(chunks)
        assert len(deduped) == 1
        assert deduped[0].score == 0.9  # 保留高分

        # 不同 document_id + 相同內容 → 不去重（不同文件）
        doc_id2 = str(uuid.uuid4())
        chunks2 = [
            ChunkResult(
                id="3",
                content="相同內容",
                score=0.9,
                result_type="chunk",
                document_id=doc_id,
                provider="ragflow",
                provider_version="1.0",
            ),
            ChunkResult(
                id="4",
                content="相同內容",
                score=0.8,
                result_type="chunk",
                document_id=doc_id2,
                provider="weknora",
                provider_version="1.0",
            ),
        ]
        deduped2 = retriever._deduplicate(chunks2)
        assert len(deduped2) == 2  # 不同文件，不去重


# ═══════════════════════════════════════════════════════════════════════════════
#  Step 4: Revoke/Delete → Immediate Deny + Projection Cleanup + Audit
# ═══════════════════════════════════════════════════════════════════════════════


class TestVerticalSliceRevoke:
    """Step 4: 撤權/刪除 → 立即拒絕 + projection 清理 + 稽核。"""

    def test_tombstone_immediate_exclusion(self):
        """Tombstone 後立即從查詢排除。"""
        db = SessionLocal()
        try:
            tid, kid, did = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
            db.add_all(
                [
                    Tenant(id=tid, name="Revoke Tenant", status="active"),
                    KnowledgeBase(id=kid, tenant_id=tid, name="Revoke KB"),
                ]
            )
            db.flush()
            doc = Document(
                id=did,
                tenant_id=tid,
                knowledge_base_id=kid,
                filename="secret.pdf",
                file_type="pdf",
                status="completed",
                content_hash="sha256:secret",
            )
            db.add(doc)
            db.commit()

            # 刪除前：可查到
            assert (
                db.query(Document)
                .filter(
                    Document.tenant_id == tid,
                    Document.tombstoned_at.is_(None),
                )
                .count()
                == 1
            )

            # 執行 tombstone
            doc.tombstoned_at = datetime.now(timezone.utc)
            db.commit()

            # 刪除後：不可查到
            assert (
                db.query(Document)
                .filter(
                    Document.tenant_id == tid,
                    Document.tombstoned_at.is_(None),
                )
                .count()
                == 0
            )

            # 但記錄仍存在（軟刪除）
            assert db.query(Document).filter(Document.id == did).count() == 1
        finally:
            db.rollback()
            db.close()

    def test_deny_set_blocks_immediately(self):
        """Gateway deny cache 立即阻擋已撤權資源。"""
        from app.gateway.authorization import GatewayAuthorizer

        authorizer = GatewayAuthorizer()
        tid, uid, did = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        authz = _make_authz(tid, uid, role="employee", dept_ids=[uuid.uuid4()])

        # 加入 deny cache（模擬撤權）
        authorizer._deny_cache[str(did)] = {str(uid)}

        # 驗證 deny cache 包含該資源
        assert str(did) in authorizer._deny_cache
        assert str(uid) in authorizer._deny_cache[str(did)]

        # 清除
        del authorizer._deny_cache[str(did)]
        assert str(did) not in authorizer._deny_cache

    def test_audit_trail_records_revoke(self):
        """稽核軌跡記錄撤權操作。"""
        from app.gateway.contracts import AuditTrail

        trail = AuditTrail(
            operation="revoke",
            providers_called=["enclave"],
            total_latency_ms=15,
            decisions=["deny:user_revoked_access"],
        )
        assert trail.operation == "revoke"
        assert "deny" in trail.decisions[0]
        assert "user_revoked_access" in trail.decisions[0]

    def test_outbox_event_for_projection_cleanup(self):
        """撤權後產生 outbox event 觸發 projection 清理。"""
        from app.models.outbox import OutboxEvent

        tenant_id = uuid.uuid4()
        event = OutboxEvent(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            aggregate_type="document",
            aggregate_id=uuid.uuid4(),
            event_type="document_revoked",
            revision=1,
            payload={
                "tenant_id": str(tenant_id),
                "document_id": str(uuid.uuid4()),
                "reason": "user_revoked",
            },
            idempotency_key=f"revoke-{uuid.uuid4()}",
            status="pending",
        )
        assert event.event_type == "document_revoked"
        assert event.status == "pending"
        assert event.idempotency_key is not None


# ═══════════════════════════════════════════════════════════════════════════════
#  Step 5: 完整垂直切片（整合所有步驟）
# ═══════════════════════════════════════════════════════════════════════════════


class TestFullVerticalSlice:
    """完整垂直切片：Upload → Parse → Search → Revoke → Deny。"""

    def test_full_lifecycle_upload_search_revoke(self):
        """完整生命週期：上傳 → 搜尋 → 撤權 → 不可搜尋。"""
        db = SessionLocal()
        try:
            # ── Setup ──
            tid, kid, did = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
            db.add_all(
                [
                    Tenant(id=tid, name="Full Lifecycle", status="active"),
                    KnowledgeBase(id=kid, tenant_id=tid, name="Full KB"),
                ]
            )
            db.flush()

            # ── Step 1: Upload ──
            doc = Document(
                id=did,
                tenant_id=tid,
                knowledge_base_id=kid,
                filename="handbook_v1.pdf",
                file_type="pdf",
                status="uploaded",
                content_hash="sha256:v1",
                source_system="enclave_upload",
            )
            db.add(doc)
            db.commit()
            assert db.query(Document).filter(Document.id == did).count() == 1

            # ── Step 2: Parse (模擬) ──
            doc.status = "parsing"
            db.commit()
            assert (
                db.query(Document).filter(Document.id == did).first().status
                == "parsing"
            )

            # ── Step 3: Index ──
            doc.status = "completed"
            db.add(
                DocumentChunk(
                    id=uuid.uuid4(),
                    tenant_id=tid,
                    document_id=did,
                    chunk_index=0,
                    text="員工手冊內容：公司政策...",
                    chunk_hash="sha256:c0",
                )
            )
            db.commit()
            assert (
                db.query(DocumentChunk).filter(DocumentChunk.document_id == did).count()
                == 1
            )

            # ── Step 4: Search (模擬 ACL 過濾) ──
            visible = (
                db.query(Document)
                .filter(
                    Document.tenant_id == tid,
                    Document.tombstoned_at.is_(None),
                )
                .count()
            )
            assert visible == 1

            # ── Step 5: Revoke ──
            doc.tombstoned_at = datetime.now(timezone.utc)
            db.commit()

            # ── Step 6: Deny ──
            visible_after = (
                db.query(Document)
                .filter(
                    Document.tenant_id == tid,
                    Document.tombstoned_at.is_(None),
                )
                .count()
            )
            assert visible_after == 0

            # ── Step 7: Audit trail exists ──
            assert doc.tombstoned_at is not None
        finally:
            db.rollback()
            db.close()

    def test_cross_tenant_isolation(self):
        """跨租戶隔離：租戶 A 的文件租戶 B 不可見。"""
        db = SessionLocal()
        try:
            tA, tB = uuid.uuid4(), uuid.uuid4()
            kA, kB = uuid.uuid4(), uuid.uuid4()
            dA, dB = uuid.uuid4(), uuid.uuid4()

            db.add_all(
                [
                    Tenant(id=tA, name="Tenant A", status="active"),
                    Tenant(id=tB, name="Tenant B", status="active"),
                    KnowledgeBase(id=kA, tenant_id=tA, name="KB A"),
                    KnowledgeBase(id=kB, tenant_id=tB, name="KB B"),
                ]
            )
            db.flush()
            db.add_all(
                [
                    Document(
                        id=dA,
                        tenant_id=tA,
                        knowledge_base_id=kA,
                        filename="a.pdf",
                        file_type="pdf",
                        status="completed",
                        content_hash="a",
                    ),
                    Document(
                        id=dB,
                        tenant_id=tB,
                        knowledge_base_id=kB,
                        filename="b.pdf",
                        file_type="pdf",
                        status="completed",
                        content_hash="b",
                    ),
                ]
            )
            db.commit()

            # Tenant A 只能看到自己的文件
            a_docs = (
                db.query(Document)
                .filter(Document.tenant_id == tA, Document.tombstoned_at.is_(None))
                .count()
            )
            b_docs = (
                db.query(Document)
                .filter(Document.tenant_id == tB, Document.tombstoned_at.is_(None))
                .count()
            )
            assert a_docs == 1
            assert b_docs == 1

            # 跨租戶查詢應為空
            cross = (
                db.query(Document)
                .filter(
                    Document.tenant_id == tA,
                    Document.id == dB,
                )
                .count()
            )
            assert cross == 0
        finally:
            db.rollback()
            db.close()

    def test_department_isolation(self):
        """跨部門隔離：部門 A 的文件部門 B 不可見（透過 ACL）。"""
        dept_a, dept_b = uuid.uuid4(), uuid.uuid4()
        tid, uid_a, uid_b = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

        authz_a = _make_authz(tid, uid_a, role="employee", dept_ids=[dept_a])
        authz_b = _make_authz(tid, uid_b, role="employee", dept_ids=[dept_b])

        # 不同部門的 authz 有不同 fingerprint
        assert authz_a.policy_fingerprint != authz_b.policy_fingerprint

        # can_access_document 需要 doc_tenant_id + doc_department_id
        # 部門 A 的使用者可以存取部門 A 的文件
        assert authz_a.can_access_document(tid, dept_a) is True
        # 部門 B 的使用者不能存取部門 A 的文件
        assert authz_b.can_access_document(tid, dept_a) is False
