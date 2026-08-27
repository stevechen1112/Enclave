"""End-to-end revocation proof across canonical and derivative data planes."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.authorization import AuthorizationContext
from app.models.asset import DerivedArtifact, EvidenceSpan
from app.models.document import Document, DocumentChunk
from app.models.graph import GraphEntity
from app.models.policy_deny import PolicyDenyEntry
from app.models.tenant import Tenant
from app.models.user import User
from app.models.wiki import WikiPage
from app.services.asset_projection import project_document
from app.services.asset_visibility import asset_access_allows
from app.services.document_revocation import DocumentRevocationService
from app.services.policy_deny import RESOURCE_WIDE_DENY_SUBJECT
from app.services.resource_policy import get_resource_policy


@pytest.fixture()
def db_session(client, test_engine):
    session = sessionmaker(bind=test_engine)()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def test_revocation_cannot_resurrect_from_projection_index_export_or_evidence(
    db_session,
) -> None:
    tenant = Tenant(id=uuid4(), name="P2 lifecycle", plan="test", status="active")
    user = User(
        id=uuid4(),
        tenant_id=tenant.id,
        email=f"p2-lifecycle-{uuid4()}@example.invalid",
        hashed_password="x",
        role="admin",
        status="active",
        is_superuser=False,
    )
    db_session.add_all([tenant, user])
    db_session.flush()
    document = Document(
        id=uuid4(),
        tenant_id=tenant.id,
        filename="revoked-procedure.txt",
        file_type="txt",
        file_path=f"s3://test/{tenant.id}/{uuid4()}.txt",
        content_hash="a" * 64,
        status="completed",
        version=1,
        uploaded_by=user.id,
    )
    db_session.add(document)
    db_session.flush()
    projection = project_document(db_session, document)
    assert projection.revision is not None
    artifact = DerivedArtifact(
        tenant_id=tenant.id,
        asset_revision_id=projection.revision.id,
        artifact_kind="extracted_text",
        content_hash="b" * 64,
        provider="p2-test",
        provider_version="1",
        quality_state="ready",
        content="old evidence",
    )
    db_session.add(artifact)
    db_session.flush()
    evidence = EvidenceSpan(
        tenant_id=tenant.id,
        artifact_id=artifact.id,
        asset_revision_id=projection.revision.id,
        locator_kind="document",
        page=1,
    )
    chunk = DocumentChunk(
        tenant_id=tenant.id,
        document_id=document.id,
        document_revision=1,
        chunk_index=0,
        text="old searchable index",
        chunk_hash="p2-lifecycle",
    )
    wiki = WikiPage(
        tenant_id=tenant.id,
        slug=f"p2-{uuid4()}",
        title="Derived page",
        page_type="summary",
        status="published",
        source_document_ids=[str(document.id)],
    )
    graph = GraphEntity(
        tenant_id=tenant.id,
        namespace="p2",
        entity_type="procedure",
        name="Derived entity",
        source_document_id=document.id,
        source_revision=1,
    )
    db_session.add_all([evidence, chunk, wiki, graph])
    db_session.commit()

    authz = AuthorizationContext(
        tenant_id=tenant.id,
        subject_id=user.id,
        role_ids=["admin"],
        is_superuser=False,
    )
    result = DocumentRevocationService().revoke(
        db_session,
        document_id=document.id,
        actor_id=user.id,
        tenant_id=tenant.id,
        reason="p2_lifecycle_test",
    )
    assert result["ok"] is True

    db_session.refresh(document)
    db_session.refresh(projection.asset)
    db_session.refresh(wiki)
    db_session.refresh(graph)
    assert document.tombstoned_at is not None
    assert projection.asset.tombstoned_at is not None
    assert wiki.tombstoned_at is not None
    assert graph.tombstoned_at is not None

    # Immutable evidence and chunks may remain for audit, but every serving
    # path must deny them after the source asset/document is tombstoned.
    assert db_session.get(EvidenceSpan, evidence.id) is not None
    assert db_session.get(DocumentChunk, chunk.id) is not None
    assert not asset_access_allows(db_session, projection.asset, authz=authz)
    assert (
        get_resource_policy().load_authorized_document(db_session, authz, document.id)
        is None
    )
    assert (
        db_session.query(DocumentChunk)
        .join(Document, DocumentChunk.document_id == Document.id)
        .filter(
            DocumentChunk.tenant_id == tenant.id,
            Document.tombstoned_at.is_(None),
        )
        .count()
        == 0
    )
    deny = (
        db_session.query(PolicyDenyEntry)
        .filter(
            PolicyDenyEntry.tenant_id == tenant.id,
            PolicyDenyEntry.resource_id == str(document.id),
            PolicyDenyEntry.subject_id == RESOURCE_WIDE_DENY_SUBJECT,
        )
        .first()
    )
    assert deny is not None
