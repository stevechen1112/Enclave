from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.core.authorization import AuthorizationContext
from app.models.asset import AssetRevision, DerivedArtifact, EvidenceSpan, SourceAsset
from app.models.knowledge_unit import (
    KnowledgeUnitRecord,
    KnowledgeUnitRelationProjection,
    KnowledgeUnitRelease,
    KnowledgeUnitReleaseMembership,
    KnowledgeUnitRevision,
)
from app.models.mka import JobRole, TenantModuleBinding
from app.models.permission import Department
from app.models.tenant import Tenant
from app.models.user import User
from app.platform.assets.contracts import (
    EvidenceLocatorKind,
    EvidenceSpan as EvidenceSpanContract,
)
from app.services.knowledge_authority_read import list_active_knowledge_units
from app.services.parse_pipeline import _markdown_evidence_chunks
from app.services.retrieval_facade import RetrievalFacade
from app.services.typed_knowledge_projection import (
    RelationCandidate,
    TypedUnitCandidate,
    expand_active_relations,
    project_typed_knowledge,
    stable_unit_key,
)


@pytest.mark.parametrize(
    "kind",
    (
        "fact",
        "definition",
        "condition",
        "exception",
        "timing",
        "formula",
        "list_member",
        "workflow_step",
        "table_fact",
        "record_field",
        "role_assignment",
        "contact",
    ),
)
def test_all_domain_neutral_typed_kinds_are_accepted(kind):
    candidate = TypedUnitCandidate(
        candidate_key=kind,
        kind=kind,
        title=kind,
        content=f"content:{kind}",
        evidence_span_id=uuid4(),
    )
    assert candidate.kind == kind


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
        EvidenceSpan.__table__,
        KnowledgeUnitRecord.__table__,
        KnowledgeUnitRevision.__table__,
        KnowledgeUnitRelease.__table__,
        KnowledgeUnitReleaseMembership.__table__,
        KnowledgeUnitRelationProjection.__table__,
    ):
        table.create(engine, checkfirst=True)
    return engine, sessionmaker(bind=engine)()


def _source(db):
    tenant = Tenant(name=f"tenant-{uuid4().hex[:8]}")
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
    asset = SourceAsset(
        tenant_id=tenant.id,
        asset_kind="document",
        title="Policy",
        source_system="upload",
        acl_reference={"visibility": "tenant"},
        current_revision=1,
        status="active",
        created_by=user.id,
    )
    db.add(asset)
    db.flush()
    revision = AssetRevision(
        tenant_id=tenant.id,
        asset_id=asset.id,
        revision=1,
        media_type="text/markdown",
        content_uri="memory://policy.md",
        content_hash="a" * 64,
        ingestion_status="ready",
        created_by=user.id,
    )
    db.add(revision)
    db.flush()
    artifact = DerivedArtifact(
        tenant_id=tenant.id,
        asset_revision_id=revision.id,
        artifact_kind="extracted_text",
        content="Policy code AX-17 requires approval.",
        content_hash="b" * 64,
        provider="enclave/native",
        provider_version="1",
        quality_state="ready",
    )
    db.add(artifact)
    db.flush()
    spans = []
    for index, section in enumerate(("Policy", "Exceptions"), 1):
        span = EvidenceSpan(
            tenant_id=tenant.id,
            artifact_id=artifact.id,
            asset_revision_id=revision.id,
            locator_kind="document",
            section=section,
            section_path=["Handbook", section],
            paragraph_index=index,
        )
        db.add(span)
        spans.append(span)
    db.flush()
    return tenant, user, asset, revision, artifact, spans


def test_heading_chain_is_preserved_and_lists_do_not_pollute_it():
    chunks = _markdown_evidence_chunks(
        "# Handbook\n- first item\n## Exceptions\n1. numbered item\n### Escalation"
    )
    assert [chunk.hierarchy for chunk in chunks] == [
        ["Handbook"],
        ["Handbook"],
        ["Handbook", "Exceptions"],
        ["Handbook", "Exceptions"],
        ["Handbook", "Exceptions", "Escalation"],
    ]
    contract = EvidenceSpanContract(
        asset_id="asset-1",
        asset_revision=1,
        locator_kind=EvidenceLocatorKind.DOCUMENT,
        section="Exceptions",
        section_path=("Handbook", "Exceptions"),
    )
    assert contract.to_dict()["section_path"] == ["Handbook", "Exceptions"]
    assert contract.to_legacy_metadata()["section_path"] == [
        "Handbook",
        "Exceptions",
    ]


@pytest.mark.parametrize(
    ("locator_kind", "locator"),
    (
        (
            EvidenceLocatorKind.TABLE,
            {"worksheet": "Sheet1", "cell_range": "B2:C4"},
        ),
        (
            EvidenceLocatorKind.AUDIO,
            {"start_ms": 1200, "end_ms": 2400, "speaker": "Operator"},
        ),
        (
            EvidenceLocatorKind.VIDEO,
            {"start_ms": 3000, "end_ms": 4500, "frame_index": 90},
        ),
    ),
)
def test_non_document_locators_survive_contract_projection(locator_kind, locator):
    contract = EvidenceSpanContract(
        asset_id="asset-1",
        asset_revision=1,
        locator_kind=locator_kind,
        **locator,
    )
    legacy = contract.to_legacy_metadata()
    assert all(legacy[key] == value for key, value in locator.items())


def test_stable_identity_binds_all_governed_coordinates():
    values = {
        "tenant_id": uuid4(),
        "source_asset_revision_id": uuid4(),
        "evidence_span_id": uuid4(),
        "kind": "fact",
        "content": "AX-17",
        "projector_version": "kq4.1",
    }
    first = stable_unit_key(**values)
    assert first == stable_unit_key(**values)
    for field, replacement in (
        ("tenant_id", uuid4()),
        ("source_asset_revision_id", uuid4()),
        ("evidence_span_id", uuid4()),
        ("kind", "definition"),
        ("content", "AX-18"),
        ("projector_version", "kq4.2"),
    ):
        assert stable_unit_key(**{**values, field: replacement}) != first


def test_typed_projection_relation_provenance_and_fail_closed_lifecycle():
    engine, db = _db()
    try:
        tenant, user, asset, revision, artifact, spans = _source(db)
        candidates = (
            TypedUnitCandidate(
                candidate_key="rule",
                kind="fact",
                title="Approval code",
                content="AX-17",
                evidence_span_id=spans[0].id,
                section_path=("Handbook", "Policy"),
            ),
            TypedUnitCandidate(
                candidate_key="exception",
                kind="exception",
                title="Emergency exception",
                content="Emergency requests use AX-99.",
                evidence_span_id=spans[1].id,
                section_path=("Handbook", "Exceptions"),
            ),
        )
        relations = (
            RelationCandidate(
                source_candidate_key="rule",
                target_candidate_key="exception",
                relation_kind="exception",
                evidence_span_id=spans[1].id,
            ),
        )
        result = project_typed_knowledge(
            db,
            tenant_id=tenant.id,
            source_asset_id=asset.id,
            source_asset_revision_id=revision.id,
            source_artifact_id=artifact.id,
            candidates=candidates,
            relations=relations,
            acl_snapshot={"visibility": "tenant"},
            created_by=user.id,
            projector_version="kq4.1",
        )
        repeated = project_typed_knowledge(
            db,
            tenant_id=tenant.id,
            source_asset_id=asset.id,
            source_asset_revision_id=revision.id,
            source_artifact_id=artifact.id,
            candidates=candidates,
            relations=relations,
            acl_snapshot={"visibility": "tenant"},
            created_by=user.id,
            projector_version="kq4.1",
        )
        assert result["unit_count"] == 2
        assert result["relation_count"] == 1
        assert repeated["relation_count"] == 0
        edge = db.query(KnowledgeUnitRelationProjection).one()
        assert edge.provenance_json == {
            "evidence_span_id": str(spans[1].id),
            "source_asset_revision_id": str(revision.id),
            "source_artifact_id": str(artifact.id),
            "projector_version": "kq4.1",
        }
        rule_revision = db.get(
            KnowledgeUnitRevision,
            UUID(result["units"]["rule"]["unit_revision_id"]),
        )
        assert rule_revision.metadata_json["typed_payload"]["kind"] == "fact"
        assert rule_revision.metadata_json["typed_payload"]["section_path"] == [
            "Handbook",
            "Policy",
        ]

        authz = AuthorizationContext(tenant_id=tenant.id, subject_id=user.id)
        visible = list_active_knowledge_units(db, authz=authz)
        assert {row.unit_type for row in visible} == {"fact", "exception"}
        expanded = expand_active_relations(
            db,
            authz=authz,
            seed_revision_ids=[result["units"]["rule"]["unit_revision_id"]],
        )
        assert [row.content for row in expanded] == [
            "Emergency requests use AX-99."
        ]

        target_membership = (
            db.query(KnowledgeUnitReleaseMembership)
            .filter(
                KnowledgeUnitReleaseMembership.release_id
                == UUID(result["units"]["exception"]["release_id"]),
                KnowledgeUnitReleaseMembership.unit_revision_id
                == UUID(result["units"]["exception"]["unit_revision_id"]),
            )
            .one()
        )
        target_membership.status = "retired"
        db.flush()
        assert (
            expand_active_relations(
                db,
                authz=authz,
                seed_revision_ids=[result["units"]["rule"]["unit_revision_id"]],
            )
            == []
        )
        target_membership.status = "active"
        db.flush()

        original_target_hash = edge.target_content_hash
        edge.target_content_hash = "0" * 64
        db.flush()
        assert (
            expand_active_relations(
                db,
                authz=authz,
                seed_revision_ids=[result["units"]["rule"]["unit_revision_id"]],
            )
            == []
        )
        edge.target_content_hash = original_target_hash
        db.flush()

        active_release_id = (
            db.query(KnowledgeUnitRelease.id)
            .filter(KnowledgeUnitRelease.status == "active")
            .scalar()
        )
        with pytest.raises(ValueError, match="unknown candidate"):
            project_typed_knowledge(
                db,
                tenant_id=tenant.id,
                source_asset_id=asset.id,
                source_asset_revision_id=revision.id,
                source_artifact_id=artifact.id,
                candidates=(
                    TypedUnitCandidate(
                        candidate_key="uncommitted",
                        kind="fact",
                        title="Must roll back",
                        content="Must roll back",
                        evidence_span_id=spans[0].id,
                    ),
                ),
                relations=(
                    RelationCandidate(
                        source_candidate_key="uncommitted",
                        target_candidate_key="missing",
                        relation_kind="member",
                        evidence_span_id=spans[0].id,
                    ),
                ),
                acl_snapshot={"visibility": "tenant"},
                created_by=user.id,
                projector_version="kq4.1",
            )
        assert (
            db.query(KnowledgeUnitRelease.id)
            .filter(KnowledgeUnitRelease.status == "active")
            .scalar()
            == active_release_id
        )
        assert (
            db.query(KnowledgeUnitRecord)
            .filter(KnowledgeUnitRecord.title == "Must roll back")
            .count()
            == 0
        )

        exception_unit = db.get(
            KnowledgeUnitRecord,
            UUID(result["units"]["exception"]["unit_id"]),
        )
        exception_unit.status = "tombstoned"
        db.flush()
        assert (
            expand_active_relations(
                db,
                authz=authz,
                seed_revision_ids=[result["units"]["rule"]["unit_revision_id"]],
            )
            == []
        )

        exception_unit.status = "active"
        revision.ingestion_status = "purged"
        db.flush()
        assert list_active_knowledge_units(db, authz=authz) == []
    finally:
        db.close()
        engine.dispose()


def test_short_code_exact_arm_ranks_exact_match_without_a_second_retriever():
    common = {
        "unit_id": uuid4(),
        "release_id": uuid4(),
        "source_resource_type": "evidence_span",
        "source_resource_id": "span",
        "source_asset_id": None,
        "source_asset_revision_id": None,
        "source_artifact_id": None,
        "metadata": {},
    }
    units = [
        SimpleNamespace(
            **common,
            unit_revision_id=uuid4(),
            unit_type="fact",
            title="Similar",
            content="AX-170 is obsolete.",
        ),
        SimpleNamespace(
            **{**common, "unit_id": uuid4()},
            unit_revision_id=uuid4(),
            unit_type="fact",
            title="Exact",
            content="Use AX-17 for approval.",
        ),
    ]
    ranked = RetrievalFacade._authority_chunks_from_units(
        units=units,
        query="AX-17",
        top_k=2,
    )
    assert ranked[0].content == "Use AX-17 for approval."
    assert ranked[0].metadata["exact_match"] is True
    assert ranked[1].metadata["exact_match"] is False
