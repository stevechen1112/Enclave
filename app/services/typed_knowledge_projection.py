"""KQ4 deterministic typed-unit and provenance relation projection."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.authorization import AuthorizationContext
from app.models.asset import AssetRevision, DerivedArtifact, EvidenceSpan, SourceAsset
from app.models.knowledge_unit import (
    KNOWLEDGE_RELATION_KINDS,
    KNOWLEDGE_UNIT_TYPES,
    KnowledgeUnitRelationProjection,
)
from app.services.knowledge_authority import publish_knowledge_unit
from app.services.knowledge_authority_read import (
    ActiveKnowledgeUnit,
    list_active_knowledge_units,
)

TYPED_KINDS = frozenset(
    {
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
    }
)
RELATION_KINDS = frozenset(KNOWLEDGE_RELATION_KINDS)


@dataclass(frozen=True)
class TypedUnitCandidate:
    candidate_key: str
    kind: str
    title: str
    content: str
    evidence_span_id: UUID
    section_path: tuple[str, ...] = ()
    subject: str | None = None
    predicate: str | None = None
    value: Any = None
    value_type: str = "text"
    conditions: tuple[str, ...] = ()
    exceptions: tuple[str, ...] = ()
    applies_to: tuple[str, ...] = ()
    topic_tags: tuple[str, ...] = ()
    entity_ids: tuple[str, ...] = ()
    effective_range: dict[str, Any] = field(default_factory=dict)
    authority_class: str = "primary_document"
    risk_level: str = "normal"
    applicability: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in TYPED_KINDS or self.kind not in KNOWLEDGE_UNIT_TYPES:
            raise ValueError(f"unsupported typed knowledge kind: {self.kind}")
        if not self.candidate_key.strip() or not self.content.strip():
            raise ValueError("candidate_key and content are required")


@dataclass(frozen=True)
class RelationCandidate:
    source_candidate_key: str
    target_candidate_key: str
    relation_kind: str
    evidence_span_id: UUID
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.relation_kind not in RELATION_KINDS:
            raise ValueError(f"unsupported knowledge relation: {self.relation_kind}")
        if self.source_candidate_key == self.target_candidate_key:
            raise ValueError("knowledge relation endpoints must be distinct")


def stable_unit_key(
    *,
    tenant_id: UUID,
    source_asset_revision_id: UUID,
    evidence_span_id: UUID,
    kind: str,
    content: str,
    projector_version: str,
) -> str:
    """Reproduce logical identity from governed source coordinates and content."""
    content_hash = hashlib.sha256(content.strip().encode("utf-8")).hexdigest()
    payload = ":".join(
        (
            str(tenant_id),
            str(source_asset_revision_id),
            str(evidence_span_id),
            kind,
            content_hash,
            projector_version,
        )
    )
    return "typed:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _relation_key(
    tenant_id: UUID,
    source_revision_id: UUID,
    target_revision_id: UUID,
    kind: str,
    evidence_span_id: UUID,
) -> str:
    payload = ":".join(
        map(
            str,
            (
                tenant_id,
                source_revision_id,
                target_revision_id,
                kind,
                evidence_span_id,
            ),
        )
    )
    return "relation:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def project_typed_knowledge(
    db: Session,
    *,
    tenant_id: UUID,
    source_asset_id: UUID,
    source_asset_revision_id: UUID,
    source_artifact_id: UUID,
    candidates: Iterable[TypedUnitCandidate],
    relations: Iterable[RelationCandidate] = (),
    acl_snapshot: dict[str, Any],
    created_by: UUID | None,
    projector_version: str,
    policy_revision: int = 1,
) -> dict[str, Any]:
    """Atomically publish one reproducible projection batch."""
    with db.begin_nested():
        return _project_typed_knowledge(
            db,
            tenant_id=tenant_id,
            source_asset_id=source_asset_id,
            source_asset_revision_id=source_asset_revision_id,
            source_artifact_id=source_artifact_id,
            candidates=candidates,
            relations=relations,
            acl_snapshot=acl_snapshot,
            created_by=created_by,
            projector_version=projector_version,
            policy_revision=policy_revision,
        )


def _project_typed_knowledge(
    db: Session,
    *,
    tenant_id: UUID,
    source_asset_id: UUID,
    source_asset_revision_id: UUID,
    source_artifact_id: UUID,
    candidates: Iterable[TypedUnitCandidate],
    relations: Iterable[RelationCandidate] = (),
    acl_snapshot: dict[str, Any],
    created_by: UUID | None,
    projector_version: str,
    policy_revision: int = 1,
) -> dict[str, Any]:
    """Publish typed units, then immutable relation edges with exact provenance."""
    candidate_rows = list(candidates)
    relation_rows = list(relations)
    if not candidate_rows:
        raise ValueError("typed projection requires at least one candidate")
    source_asset = (
        db.query(SourceAsset.id)
        .filter(
            SourceAsset.tenant_id == tenant_id,
            SourceAsset.id == source_asset_id,
            SourceAsset.status == "active",
            SourceAsset.tombstoned_at.is_(None),
        )
        .first()
    )
    source_revision = (
        db.query(AssetRevision.id)
        .filter(
            AssetRevision.tenant_id == tenant_id,
            AssetRevision.id == source_asset_revision_id,
            AssetRevision.asset_id == source_asset_id,
            AssetRevision.ingestion_status == "ready",
        )
        .first()
    )
    source_artifact = (
        db.query(DerivedArtifact.id)
        .filter(
            DerivedArtifact.tenant_id == tenant_id,
            DerivedArtifact.id == source_artifact_id,
            DerivedArtifact.asset_revision_id == source_asset_revision_id,
            DerivedArtifact.quality_state == "ready",
        )
        .first()
    )
    if source_asset is None or source_revision is None or source_artifact is None:
        raise ValueError("typed projection source is not active and ready")
    evidence_span_ids = {
        row.evidence_span_id for row in (*candidate_rows, *relation_rows)
    }
    valid_span_count = (
        db.query(EvidenceSpan.id)
        .filter(
            EvidenceSpan.tenant_id == tenant_id,
            EvidenceSpan.id.in_(evidence_span_ids),
            EvidenceSpan.artifact_id == source_artifact_id,
            EvidenceSpan.asset_revision_id == source_asset_revision_id,
        )
        .count()
    )
    if valid_span_count != len(evidence_span_ids):
        raise ValueError("typed projection evidence lineage mismatch")
    by_key: dict[str, dict[str, Any]] = {}
    candidate_by_key: dict[str, TypedUnitCandidate] = {}
    for candidate in candidate_rows:
        if candidate.candidate_key in by_key:
            raise ValueError(f"duplicate candidate key: {candidate.candidate_key}")
        unit_key = stable_unit_key(
            tenant_id=tenant_id,
            source_asset_revision_id=source_asset_revision_id,
            evidence_span_id=candidate.evidence_span_id,
            kind=candidate.kind,
            content=candidate.content,
            projector_version=projector_version,
        )
        result = publish_knowledge_unit(
            db,
            tenant_id=tenant_id,
            unit_key=unit_key,
            unit_type=candidate.kind,
            title=candidate.title,
            content=candidate.content,
            authority_class=candidate.authority_class,
            acl_snapshot=acl_snapshot,
            source_resource_type="evidence_span",
            source_resource_id=str(candidate.evidence_span_id),
            source_asset_id=source_asset_id,
            source_asset_revision_id=source_asset_revision_id,
            source_artifact_id=source_artifact_id,
            risk_level=candidate.risk_level,
            applicability=dict(candidate.applicability),
            metadata={
                **dict(candidate.metadata),
                "typed_payload": {
                    "schema_version": "1.0",
                    "kind": candidate.kind,
                    "subject": candidate.subject,
                    "predicate": candidate.predicate,
                    "value": candidate.value,
                    "value_type": candidate.value_type,
                    "statement": candidate.content,
                    "conditions": list(candidate.conditions),
                    "exceptions": list(candidate.exceptions),
                    "applies_to": list(candidate.applies_to),
                    "topic_tags": list(candidate.topic_tags),
                    "entity_ids": list(candidate.entity_ids),
                    "authority_class": candidate.authority_class,
                    "effective_range": dict(candidate.effective_range),
                    "risk_class": candidate.risk_level,
                    "source_span_id": str(candidate.evidence_span_id),
                    "exact_quote": candidate.content,
                    "section_path": list(candidate.section_path),
                    "content_hash": hashlib.sha256(
                        candidate.content.strip().encode("utf-8")
                    ).hexdigest(),
                    "projector_version": projector_version,
                },
            },
            policy_revision=policy_revision,
            created_by=created_by,
            gate_evidence={
                "projector_version": projector_version,
                "source_asset_revision_id": str(source_asset_revision_id),
            },
        )
        by_key[candidate.candidate_key] = result
        candidate_by_key[candidate.candidate_key] = candidate

    relation_count = 0
    for relation in relation_rows:
        if (
            relation.source_candidate_key not in by_key
            or relation.target_candidate_key not in by_key
        ):
            raise ValueError("relation references an unknown candidate")
        source_revision_id = UUID(by_key[relation.source_candidate_key]["unit_revision_id"])
        target_revision_id = UUID(by_key[relation.target_candidate_key]["unit_revision_id"])
        relation_key = _relation_key(
            tenant_id,
            source_revision_id,
            target_revision_id,
            relation.relation_kind,
            relation.evidence_span_id,
        )
        existing = (
            db.query(KnowledgeUnitRelationProjection)
            .filter(
                KnowledgeUnitRelationProjection.tenant_id == tenant_id,
                KnowledgeUnitRelationProjection.relation_key == relation_key,
            )
            .first()
        )
        if existing is None:
            db.add(
                KnowledgeUnitRelationProjection(
                    tenant_id=tenant_id,
                    relation_key=relation_key,
                    source_revision_id=source_revision_id,
                    target_revision_id=target_revision_id,
                    relation_kind=relation.relation_kind,
                    source_content_hash=hashlib.sha256(
                        candidate_by_key[relation.source_candidate_key]
                        .content.strip()
                        .encode("utf-8")
                    ).hexdigest(),
                    target_content_hash=hashlib.sha256(
                        candidate_by_key[relation.target_candidate_key]
                        .content.strip()
                        .encode("utf-8")
                    ).hexdigest(),
                    projector_version=projector_version,
                    provenance_json={
                        "evidence_span_id": str(relation.evidence_span_id),
                        "source_asset_revision_id": str(source_asset_revision_id),
                        "source_artifact_id": str(source_artifact_id),
                        "projector_version": projector_version,
                        **dict(relation.metadata),
                    },
                    created_by=created_by,
                )
            )
            relation_count += 1
    db.flush()
    return {
        "units": by_key,
        "unit_count": len(by_key),
        "relation_count": relation_count,
        "projector_version": projector_version,
    }


def expand_active_relations(
    db: Session,
    *,
    authz: AuthorizationContext,
    seed_revision_ids: Iterable[UUID],
    relation_kinds: Iterable[str] = RELATION_KINDS,
    kb_revision_ids: Iterable[UUID] | None = None,
    query_text: str | None = None,
) -> list[ActiveKnowledgeUnit]:
    """Expand only to endpoints that independently pass live authority checks."""
    seeds = {UUID(str(value)) for value in seed_revision_ids}
    kinds = {str(value) for value in relation_kinds}
    if not seeds or not kinds or not kinds.issubset(RELATION_KINDS):
        return []
    visible = list_active_knowledge_units(
        db,
        authz=authz,
        kb_revision_ids=kb_revision_ids,
        query_text=query_text,
    )
    visible_by_revision = {row.unit_revision_id: row for row in visible}
    edges = (
        db.query(KnowledgeUnitRelationProjection)
        .filter(
            KnowledgeUnitRelationProjection.tenant_id == authz.tenant_id,
            KnowledgeUnitRelationProjection.source_revision_id.in_(seeds),
            KnowledgeUnitRelationProjection.relation_kind.in_(kinds),
        )
        .all()
    )
    target_ids: set[UUID] = set()
    for edge in edges:
        source = visible_by_revision.get(edge.source_revision_id)
        target = visible_by_revision.get(edge.target_revision_id)
        if source is None or target is None or source.release_id != target.release_id:
            continue
        if hashlib.sha256(source.content.encode("utf-8")).hexdigest() != str(
            edge.source_content_hash
        ):
            continue
        if hashlib.sha256(target.content.encode("utf-8")).hexdigest() != str(
            edge.target_content_hash
        ):
            continue
        target_ids.add(edge.target_revision_id)
    return [
        visible_by_revision[item]
        for item in sorted(target_ids, key=str)
        if item in visible_by_revision
    ]


def projection_manifest_hash(result: dict[str, Any]) -> str:
    """Stable content-free digest suitable for gate evidence."""
    payload = {
        "units": {
            key: {
                field: value
                for field, value in row.items()
                if field in {"unit_id", "unit_revision_id", "release_id"}
            }
            for key, row in sorted((result.get("units") or {}).items())
        },
        "relation_count": int(result.get("relation_count") or 0),
        "projector_version": result.get("projector_version"),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
