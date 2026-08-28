from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import sessionmaker

from app.api.v1.endpoints.kb import SearchRequest, search_knowledge_base
from app.config import settings
from app.core.authorization import AuthorizationContext
from app.models.document import Document, DocumentChunk
from app.models.knowledge_engine import KnowledgeBaseRevisionDocument
from app.models.tenant import Tenant
from app.services.kb_scope_policy import resolve_kb_revision_scope
from app.services.p5_staging_fixture import activate_staging_capacity_fixture
from scripts.prepare_p5_grounded_fixture import (
    _asset_is_ready,
    _chat_is_grounded,
    _search_has_marker,
)


def test_search_marker_must_exist_in_retrieved_content():
    assert _search_has_marker(
        {"results": [{"content": "Procedure P5-SOP-RESET-042"}]},
        "P5-SOP-RESET-042",
    )
    assert not _search_has_marker(
        {"results": [{"content": "unrelated recovery data"}]},
        "P5-SOP-RESET-042",
    )


def test_grounded_chat_requires_answer_and_sources():
    assert _chat_is_grounded({"answer": "先確認壓力歸零", "sources": [{"id": "1"}]})
    assert not _chat_is_grounded({"answer": "無資料", "sources": []})


def test_document_asset_readiness_uses_canonical_revision_state():
    assert _asset_is_ready(
        {"status": "active", "revision": {"ingestion_status": "ready"}}
    )
    assert not _asset_is_ready(
        {"status": "active", "revision": {"ingestion_status": "pending"}}
    )
    assert not _asset_is_ready({"status": "active"})


def test_public_search_passes_explicit_active_revision_scope_to_retrieval():
    authz = MagicMock()
    facade = MagicMock()
    facade.search.return_value = SimpleNamespace(results=[])
    scope = {"kb_revision_ids": []}
    with patch(
        "app.core.authorization.AuthorizationContext.from_user", return_value=authz
    ), patch(
        "app.services.kb_scope_policy.resolve_kb_revision_scope", return_value=scope
    ) as resolver, patch(
        "app.services.retrieval_facade.get_retrieval_facade", return_value=facade
    ):
        response = search_knowledge_base(
            request=SearchRequest(query="P5-SOP-RESET-042"),
            db=MagicMock(),
            current_user=MagicMock(),
        )

    resolver.assert_called_once()
    assert facade.search.call_args.kwargs["scope"] == scope
    assert response.total_results == 0


def test_public_catalog_search_uses_the_same_revision_scope():
    authz = MagicMock()
    facade = MagicMock()
    facade.search_catalog.return_value = []
    scope = {"kb_revision_ids": []}
    with patch(
        "app.core.authorization.AuthorizationContext.from_user", return_value=authz
    ), patch(
        "app.services.kb_scope_policy.resolve_kb_revision_scope", return_value=scope
    ), patch(
        "app.services.retrieval_facade.get_retrieval_facade", return_value=facade
    ):
        response = search_knowledge_base(
            request=SearchRequest(query="有哪些文件", granularity="catalog"),
            db=MagicMock(),
            current_user=MagicMock(),
        )

    assert facade.search_catalog.call_args.kwargs["filters"] == scope
    assert response.granularity == "catalog"


def test_auto_search_uses_chunk_evidence_for_difference_question():
    authz = MagicMock()
    facade = MagicMock()
    facade.search.return_value = SimpleNamespace(results=[])
    with patch(
        "app.core.authorization.AuthorizationContext.from_user", return_value=authz
    ), patch(
        "app.services.kb_scope_policy.resolve_kb_revision_scope",
        return_value={"kb_revision_ids": []},
    ), patch(
        "app.services.retrieval_facade.get_retrieval_facade", return_value=facade
    ):
        response = search_knowledge_base(
            request=SearchRequest(
                query="P5-SOP-RESET-042 盤點差異", granularity="auto"
            ),
            db=MagicMock(),
            current_user=MagicMock(),
        )

    facade.search.assert_called_once()
    facade.search_catalog.assert_not_called()
    assert response.granularity == "chunk"


def test_capacity_fixture_activation_is_staging_only(test_engine, monkeypatch):
    db = sessionmaker(bind=test_engine)()
    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    try:
        monkeypatch.setattr(settings, "APP_ENV", "production")
        with pytest.raises(RuntimeError, match="APP_ENV=staging"):
            activate_staging_capacity_fixture(
                db,
                tenant_id=tenant_id,
                document_id=document_id,
                marker="P5-SOP-RESET-042",
                confirm_isolated_staging=True,
            )
    finally:
        db.rollback()
        db.close()


def test_capacity_fixture_creates_one_explicit_active_revision(test_engine, monkeypatch):
    db = sessionmaker(bind=test_engine)()
    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    try:
        tenant = Tenant(
            id=tenant_id,
            name=f"p5-fixture-{tenant_id}",
            status="active",
        )
        document = Document(
            id=document_id,
            tenant_id=tenant_id,
            filename="p5_grounded_sop.md",
            file_type="md",
            status="completed",
            version=1,
            chunk_count=1,
        )
        chunk = DocumentChunk(
            tenant_id=tenant_id,
            document_id=document_id,
            document_revision=1,
            chunk_index=0,
            text="Synthetic procedure P5-SOP-RESET-042: pressure must be zero.",
        )
        db.add_all([tenant, document, chunk])
        db.flush()
        monkeypatch.setattr(settings, "APP_ENV", "staging")

        revision = activate_staging_capacity_fixture(
            db,
            tenant_id=tenant_id,
            document_id=document_id,
            marker="P5-SOP-RESET-042",
            confirm_isolated_staging=True,
        )

        assert revision.status == "active"
        assert revision.manifest_json["formal_release"] is False
        membership = (
            db.query(KnowledgeBaseRevisionDocument)
            .filter(KnowledgeBaseRevisionDocument.kb_revision_id == revision.id)
            .one()
        )
        assert membership.document_id == document_id
        scope = resolve_kb_revision_scope(
            authz=AuthorizationContext(
                tenant_id=tenant_id,
                subject_id=uuid.uuid4(),
                role_ids=["employee"],
            ),
            requested=None,
            db=db,
        )
        assert scope == {"kb_revision_ids": [str(revision.id)]}
    finally:
        db.rollback()
        db.close()
