from __future__ import annotations

import uuid

from sqlalchemy.orm import sessionmaker

from app.models.document import Document, DocumentChunk
from app.models.kb_maintenance import DocumentVersion
from app.models.knowledge_base import KnowledgeBase, KnowledgeBaseRevision
from app.models.knowledge_engine import DocumentProfile, KnowledgeBaseRevisionDocument
from app.models.tenant import Tenant
from app.services.document_readiness import (
    apply_answer_ready_filter,
    load_document_answer_states,
)


def _published_document(db, *, status="completed", version=1, profile_ready=True, with_chunk=True):
    tenant = Tenant(id=uuid.uuid4(), name=f"readiness-{uuid.uuid4().hex}", status="active")
    document = Document(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        filename="manual.txt",
        file_type="txt",
        status=status,
        version=version,
    )
    kb = KnowledgeBase(
        id=uuid.uuid4(), tenant_id=tenant.id, name="Published", status="active", active_revision=1
    )
    db.add_all([tenant, document, kb])
    db.flush()
    document_version = DocumentVersion(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        document_id=document.id,
        version=1,
        filename=document.filename,
        status="completed",
        content_snapshot="published content",
    )
    revision = KnowledgeBaseRevision(
        id=uuid.uuid4(), kb_id=kb.id, revision=1, status="active", manifest_json={}
    )
    db.add_all([document_version, revision])
    db.flush()
    db.add(
        KnowledgeBaseRevisionDocument(
            tenant_id=tenant.id,
            kb_revision_id=revision.id,
            document_id=document.id,
            document_version_id=document_version.id,
            document_revision=1,
            content_hash="a" * 64,
            acl_snapshot={},
            policy_revision=1,
        )
    )
    db.add(
        DocumentProfile(
            tenant_id=tenant.id,
            document_id=document.id,
            document_revision=1,
            format_family="text",
            support_level="full",
            language_profile={},
            structure_map={},
            capability_readiness={"narrative": profile_ready},
            warnings=[],
            answer_ready=profile_ready,
            profiler_version="test",
            content_hash="a" * 64,
        )
    )
    if with_chunk:
        db.add(
            DocumentChunk(
                tenant_id=tenant.id,
                document_id=document.id,
                document_revision=1,
                chunk_index=0,
                text="published content",
                chunk_hash=uuid.uuid4().hex,
            )
        )
    db.flush()
    return tenant, document


def test_canonical_readiness_requires_profile_chunks_and_active_membership(test_engine):
    db = sessionmaker(bind=test_engine)()
    try:
        tenant, document = _published_document(db, profile_ready=True, with_chunk=True)
        state = load_document_answer_states(
            db, tenant_id=tenant.id, documents=[document]
        )[document.id]

        assert state.answer_ready is True
        assert state.published_revision == 1
        assert state.published_chunk_count == 1
        assert state.readiness_reasons == ()
        visible = apply_answer_ready_filter(
            db.query(Document), tenant_id=tenant.id, db=db
        ).all()
        assert document in visible
        assert apply_answer_ready_filter(
            db.query(Document), tenant_id=tenant.id, db=db, kb_revision_ids=[]
        ).all() == []
        scoped_state = load_document_answer_states(
            db, tenant_id=tenant.id, documents=[document], kb_revision_ids=[]
        )[document.id]
        assert scoped_state.answer_ready is False
        assert scoped_state.readiness_reasons == ("not_in_active_revision",)
    finally:
        db.rollback()
        db.close()


def test_completed_alone_is_not_answer_ready(test_engine):
    db = sessionmaker(bind=test_engine)()
    try:
        tenant, document = _published_document(db, profile_ready=False, with_chunk=False)
        state = load_document_answer_states(
            db, tenant_id=tenant.id, documents=[document]
        )[document.id]

        assert state.answer_ready is False
        assert set(state.readiness_reasons) == {"profile_not_answer_ready", "chunks_missing"}
        visible = apply_answer_ready_filter(
            db.query(Document), tenant_id=tenant.id, db=db
        ).all()
        assert document not in visible
    finally:
        db.rollback()
        db.close()


def test_new_failed_revision_does_not_withdraw_older_published_revision(test_engine):
    db = sessionmaker(bind=test_engine)()
    try:
        tenant, document = _published_document(
            db, status="failed", version=2, profile_ready=True, with_chunk=True
        )
        state = load_document_answer_states(
            db, tenant_id=tenant.id, documents=[document]
        )[document.id]

        assert state.answer_ready is True
        assert state.published_revision == 1
    finally:
        db.rollback()
        db.close()
