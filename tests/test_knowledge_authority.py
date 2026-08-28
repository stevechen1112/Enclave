from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.core.authorization import AuthorizationContext
from app.models.asset import AssetRevision, DerivedArtifact, SourceAsset
from app.models.document import Document, DocumentChunk
from app.models.kb_maintenance import DocumentVersion
from app.models.knowledge_base import KnowledgeBase, KnowledgeBaseRevision
from app.models.knowledge_engine import KnowledgeBaseRevisionDocument
from app.models.knowledge_unit import (
    KnowledgeUnitRecord,
    KnowledgeUnitRelease,
    KnowledgeUnitReleaseMembership,
    KnowledgeUnitRevision,
)
from app.models.mka import JobRole, TenantModuleBinding
from app.models.permission import Department
from app.models.tenant import Tenant
from app.models.user import User
from app.services.knowledge_authority import (
    publish_approved_knowhow,
    publish_document_kb_revision,
    publish_knowledge_unit,
    retire_knowledge_unit,
)
from app.services.knowledge_authority_read import (
    list_active_knowledge_units,
    sealed_parity_report,
)


def _db():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    for table in (
        Tenant.__table__,
        Department.__table__,
        JobRole.__table__,
        TenantModuleBinding.__table__,
        User.__table__,
        SourceAsset.__table__,
        AssetRevision.__table__,
        DerivedArtifact.__table__,
        KnowledgeUnitRecord.__table__,
        KnowledgeUnitRevision.__table__,
        KnowledgeUnitRelease.__table__,
        KnowledgeUnitReleaseMembership.__table__,
    ):
        table.create(engine, checkfirst=True)
    return engine, sessionmaker(bind=engine)()


def _document_db():
    engine, db = _db()
    for table in (
        KnowledgeBase.__table__,
        KnowledgeBaseRevision.__table__,
        Document.__table__,
        DocumentVersion.__table__,
        DocumentChunk.__table__,
        KnowledgeBaseRevisionDocument.__table__,
    ):
        table.create(engine, checkfirst=True)
    return engine, db


def _publish(db, tenant, user, *, key, content):
    return publish_knowledge_unit(
        db,
        tenant_id=tenant.id,
        unit_key=key,
        unit_type="procedure",
        title=key,
        content=content,
        authority_class="reviewed_test",
        acl_snapshot={"visibility": "tenant"},
        source_resource_type="test",
        source_resource_id=key,
        created_by=user.id,
        gate_evidence={"test": True},
    )


def test_publication_creates_immutable_release_images_and_is_idempotent():
    engine, db = _db()
    try:
        tenant = Tenant(name=f"tenant-{uuid4().hex[:6]}")
        db.add(tenant)
        db.flush()
        user = User(
            tenant_id=tenant.id,
            email=f"{uuid4().hex}@example.invalid",
            hashed_password="x",
            role="admin",
            status="active",
        )
        db.add(user)
        db.flush()

        first = _publish(db, tenant, user, key="procedure:a", content="A1")
        second = _publish(db, tenant, user, key="procedure:b", content="B1")
        third = _publish(db, tenant, user, key="procedure:a", content="A2")
        repeated = _publish(db, tenant, user, key="procedure:a", content="A2")

        assert first["release_id"] != second["release_id"] != third["release_id"]
        assert repeated["release_id"] == third["release_id"]
        assert repeated["idempotent"] is True
        assert db.query(KnowledgeUnitRecord).count() == 2
        assert db.query(KnowledgeUnitRevision).count() == 3

        releases = db.query(KnowledgeUnitRelease).order_by(
            KnowledgeUnitRelease.revision
        ).all()
        assert [release.status for release in releases] == [
            "retired",
            "retired",
            "active",
        ]
        assert [
            db.query(KnowledgeUnitReleaseMembership)
            .filter(KnowledgeUnitReleaseMembership.release_id == release.id)
            .count()
            for release in releases
        ] == [1, 2, 2]

        active_members = (
            db.query(KnowledgeUnitReleaseMembership, KnowledgeUnitRevision)
            .join(
                KnowledgeUnitRevision,
                KnowledgeUnitRevision.id
                == KnowledgeUnitReleaseMembership.unit_revision_id,
            )
            .filter(
                KnowledgeUnitReleaseMembership.release_id == releases[-1].id
            )
            .all()
        )
        assert {revision.content for _, revision in active_members} == {"A2", "B1"}
    finally:
        db.close()
        engine.dispose()


def test_active_authority_read_is_tenant_scoped_deny_first_and_reportable():
    engine, db = _db()
    try:
        tenant = Tenant(name=f"tenant-{uuid4().hex[:6]}")
        other_tenant = Tenant(name=f"tenant-{uuid4().hex[:6]}")
        db.add_all([tenant, other_tenant])
        db.flush()
        user = User(
            tenant_id=tenant.id,
            email=f"{uuid4().hex}@example.invalid",
            hashed_password="x",
            role="viewer",
            status="active",
        )
        other_user = User(
            tenant_id=other_tenant.id,
            email=f"{uuid4().hex}@example.invalid",
            hashed_password="x",
            role="viewer",
            status="active",
        )
        db.add_all([user, other_user])
        db.flush()
        _publish(db, tenant, user, key="visible", content="visible text")
        publish_knowledge_unit(
            db,
            tenant_id=tenant.id,
            unit_key="denied",
            unit_type="knowhow",
            title="denied",
            content="denied text",
            authority_class="reviewed_test",
            acl_snapshot={
                "visibility": "tenant",
                "denied_subject_ids": [str(user.id)],
            },
            source_resource_type="test",
            source_resource_id="denied",
            created_by=user.id,
        )
        _publish(db, other_tenant, other_user, key="foreign", content="foreign text")

        authz = AuthorizationContext(
            tenant_id=tenant.id,
            subject_id=user.id,
            role_ids=("viewer",),
        )
        rows = list_active_knowledge_units(db, authz=authz)
        assert [row.source_resource_id for row in rows] == ["visible"]
        assert list_active_knowledge_units(db, authz=authz, kb_revision_ids=[]) == []
        assert sealed_parity_report(
            legacy_resource_ids=["visible"], authority_units=rows
        )["status"] == "match"
    finally:
        db.close()
        engine.dispose()


def test_document_release_is_exactly_scoped_to_legacy_kb_revision():
    engine, db = _document_db()
    try:
        tenant = Tenant(name=f"tenant-{uuid4().hex[:6]}")
        db.add(tenant)
        db.flush()
        user = User(
            tenant_id=tenant.id,
            email=f"{uuid4().hex}@example.invalid",
            hashed_password="x",
            role="viewer",
            status="active",
        )
        db.add(user)
        db.flush()
        kb = KnowledgeBase(tenant_id=tenant.id, name="Operations")
        db.add(kb)
        db.flush()
        document = Document(
            tenant_id=tenant.id,
            knowledge_base_id=kb.id,
            filename="manual.txt",
            version=1,
            status="completed",
            uploaded_by=user.id,
        )
        db.add(document)
        db.flush()
        snapshot = DocumentVersion(
            tenant_id=tenant.id,
            document_id=document.id,
            version=1,
            filename=document.filename,
            status="completed",
            uploaded_by=user.id,
            content_snapshot="first\nsecond",
        )
        revision = KnowledgeBaseRevision(
            kb_id=kb.id,
            revision=1,
            manifest_hash="a" * 64,
            policy_revision=1,
            status="active",
        )
        db.add_all([snapshot, revision])
        db.flush()
        chunks = [
            DocumentChunk(
                tenant_id=tenant.id,
                document_id=document.id,
                document_revision=1,
                chunk_index=index,
                text=text,
            )
            for index, text in enumerate(("first", "second"))
        ]
        db.add_all(chunks)
        db.flush()
        db.add(
            KnowledgeBaseRevisionDocument(
                tenant_id=tenant.id,
                kb_revision_id=revision.id,
                document_id=document.id,
                document_version_id=snapshot.id,
                document_revision=1,
                content_hash="b" * 64,
                acl_snapshot={"visibility": "tenant"},
                policy_revision=1,
            )
        )
        db.flush()
        result = publish_document_kb_revision(
            db, kb=kb, kb_revision=revision, created_by=user.id
        )
        authz = AuthorizationContext(
            tenant_id=tenant.id,
            subject_id=user.id,
            role_ids=("viewer",),
        )
        scoped = list_active_knowledge_units(
            db, authz=authz, kb_revision_ids=[revision.id]
        )
        assert result["unit_count"] == 2
        assert {row.content for row in scoped} == {"first", "second"}
        assert len(list_active_knowledge_units(db, authz=authz)) == 2
    finally:
        db.close()
        engine.dispose()


def test_approved_knowhow_publishes_to_tenant_release():
    engine, db = _db()
    try:
        tenant = Tenant(name=f"tenant-{uuid4().hex[:6]}")
        db.add(tenant)
        db.flush()
        user = User(
            tenant_id=tenant.id,
            email=f"{uuid4().hex}@example.invalid",
            hashed_password="x",
            role="viewer",
            status="active",
        )
        db.add(user)
        db.flush()
        db.add(
            TenantModuleBinding(
                tenant_id=tenant.id,
                module_key="training_knowhow",
                enabled=True,
                license_state="active",
            )
        )
        db.flush()
        card = SimpleNamespace(
            id=uuid4(),
            tenant_id=tenant.id,
            owner_id=user.id,
            card_id="KH-001",
            title="換線檢查",
            summary="先確認能源隔離",
            steps=["停機", "上鎖"],
            recommended_actions=[],
            prerequisites=[],
            cautions=[],
            risks=["夾傷"],
            prohibited_actions=[],
            source_quotes=[],
            related_sop_ids=[],
            risk_level="high",
            applicable_roles=["operator"],
            equipment_ids=["M-1"],
            product_ids=[],
            customer_ids=[],
            source_type="manual",
            source_document_id=None,
            authority_level=90,
            version=1,
        )
        result = publish_approved_knowhow(db, card=card, reviewer_id=user.id)
        authz = AuthorizationContext(
            tenant_id=tenant.id,
            subject_id=user.id,
            role_ids=("operator",),
        )
        rows = list_active_knowledge_units(
            db, authz=authz, query_text="M-1 換線"
        )
        assert result["idempotent"] is False
        assert len(rows) == 1
        assert rows[0].unit_type == "knowhow"
        assert rows[0].source_resource_id == str(card.id)
        assert rows[0].metadata["deep_link"] == f"/knowhow/{card.id}"
        retired = retire_knowledge_unit(
            db,
            tenant_id=tenant.id,
            unit_key=f"knowhow:{card.id}",
            retired_by=user.id,
        )
        assert retired["idempotent"] is False
        assert list_active_knowledge_units(
            db, authz=authz, query_text="M-1 換線"
        ) == []
    finally:
        db.close()
        engine.dispose()
