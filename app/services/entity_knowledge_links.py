"""Canonical entity projection and bounded cross-source expansion (AV5)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.core.authorization import AuthorizationContext
from app.models.knowledge_engine import EntityAlias, EntityRegistry
from app.models.media_analysis import (
    AssetEntityLink,
    EntityRelationship,
    KnowledgeUnitEntityLink,
)
from app.services.entity_registry import normalize_entity, resolve_entity


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()


def resolve_entities_in_query(
    db: Session, *, tenant_id: UUID, query: str
) -> dict[str, Any]:
    normalized_query = normalize_entity(query)
    entities = (
        db.query(EntityRegistry)
        .filter(
            EntityRegistry.tenant_id == tenant_id, EntityRegistry.status == "active"
        )
        .all()
    )
    aliases = (
        db.query(EntityAlias)
        .filter(EntityAlias.tenant_id == tenant_id, EntityAlias.approved.is_(True))
        .all()
    )
    names: dict[UUID, set[str]] = {
        entity.id: {entity.canonical_key, entity.display_name} for entity in entities
    }
    for alias in aliases:
        names.setdefault(alias.entity_id, set()).add(alias.alias)
    matched = {
        entity_id: sorted(
            {
                name
                for name in values
                if normalize_entity(name) and normalize_entity(name) in normalized_query
            }
        )
        for entity_id, values in names.items()
    }
    matched = {entity_id: values for entity_id, values in matched.items() if values}
    normalized_name_owners: dict[str, set[UUID]] = {}
    for entity_id, values in matched.items():
        for value in values:
            normalized_name_owners.setdefault(normalize_entity(value), set()).add(
                entity_id
            )
    ambiguous_ids = {
        entity_id
        for owners in normalized_name_owners.values()
        if len(owners) > 1
        for entity_id in owners
    }
    return {
        "resolved_entity_ids": tuple(
            sorted((item for item in matched if item not in ambiguous_ids), key=str)
        ),
        "ambiguous_entity_ids": tuple(sorted(ambiguous_ids, key=str)),
        "matched_names": {str(key): value for key, value in matched.items()},
    }


def project_asset_entity_link(
    db: Session,
    *,
    tenant_id: UUID,
    asset_revision_id: UUID,
    entity_id: UUID,
    link_kind: str,
    status: str,
    confidence: float | None,
    evidence: list[dict[str, Any]],
    projector_version: str,
) -> AssetEntityLink:
    source_hash = _hash(evidence)
    row = (
        db.query(AssetEntityLink)
        .filter(
            AssetEntityLink.tenant_id == tenant_id,
            AssetEntityLink.asset_revision_id == asset_revision_id,
            AssetEntityLink.entity_id == entity_id,
            AssetEntityLink.link_kind == link_kind,
            AssetEntityLink.projector_version == projector_version,
            AssetEntityLink.source_hash == source_hash,
        )
        .first()
    )
    if row is None:
        row = AssetEntityLink(
            tenant_id=tenant_id,
            asset_revision_id=asset_revision_id,
            entity_id=entity_id,
            link_kind=link_kind,
            status=status,
            confidence=confidence,
            evidence_json=evidence,
            projector_version=projector_version,
            source_hash=source_hash,
        )
        db.add(row)
        db.flush()
    return row


def project_unit_entity_links(
    db: Session,
    *,
    tenant_id: UUID,
    unit_revision_id: UUID,
    entity_ids: Iterable[str | UUID],
    projector_version: str,
    evidence: list[dict[str, Any]],
) -> list[KnowledgeUnitEntityLink]:
    requested: list[UUID] = []
    for value in entity_ids:
        try:
            requested.append(UUID(str(value)))
        except (TypeError, ValueError):
            continue
    existing_entities = (
        {
            row.id
            for row in db.query(EntityRegistry.id)
            .filter(
                EntityRegistry.tenant_id == tenant_id,
                EntityRegistry.id.in_(requested),
                EntityRegistry.status == "active",
            )
            .all()
        }
        if requested
        else set()
    )
    source_hash = _hash(evidence)
    rows: list[KnowledgeUnitEntityLink] = []
    for entity_id in requested:
        if entity_id not in existing_entities:
            continue
        row = (
            db.query(KnowledgeUnitEntityLink)
            .filter(
                KnowledgeUnitEntityLink.tenant_id == tenant_id,
                KnowledgeUnitEntityLink.unit_revision_id == unit_revision_id,
                KnowledgeUnitEntityLink.entity_id == entity_id,
                KnowledgeUnitEntityLink.link_kind == "about",
                KnowledgeUnitEntityLink.projector_version == projector_version,
                KnowledgeUnitEntityLink.source_hash == source_hash,
            )
            .first()
        )
        if row is None:
            row = KnowledgeUnitEntityLink(
                tenant_id=tenant_id,
                unit_revision_id=unit_revision_id,
                entity_id=entity_id,
                link_kind="about",
                status="approved",
                confidence=1.0,
                evidence_json=evidence,
                projector_version=projector_version,
                source_hash=source_hash,
            )
            db.add(row)
            db.flush()
        rows.append(row)
    return rows


def project_asset_entities_from_metadata(
    db: Session,
    *,
    tenant_id: UUID,
    asset_revision_id: UUID,
    metadata: dict[str, Any],
    projector_version: str = "media-entity-metadata.v1",
) -> dict[str, Any]:
    """Resolve explicit intake metadata without creating canonical entities.

    Exact canonical names and approved aliases become approved links. Ambiguous
    values remain review candidates and are never admitted by retrieval.
    """
    field_types = {
        "entity_ids": None,
        "equipment_ids": "equipment",
        "product_ids": "product",
        "customer_ids": "customer",
        "process_ids": "process",
        "site_ids": "site",
    }
    resolved_count = ambiguous_count = unresolved_count = 0
    for field_name, entity_type in field_types.items():
        raw_values = metadata.get(field_name) or []
        if isinstance(raw_values, str):
            raw_values = [raw_values]
        for raw_value in raw_values:
            value = str(raw_value or "").strip()
            if not value:
                continue
            resolution = resolve_entity(
                db, tenant_id=tenant_id, value=value, entity_type=entity_type
            )
            evidence = [
                {"kind": "intake_metadata", "field": field_name, "value": value}
            ]
            if resolution.status == "not_found":
                unresolved_count += 1
                continue
            status = "approved" if resolution.status == "resolved" else "candidate"
            confidence = 1.0 if status == "approved" else None
            for entity_id in resolution.entity_ids:
                project_asset_entity_link(
                    db,
                    tenant_id=tenant_id,
                    asset_revision_id=asset_revision_id,
                    entity_id=UUID(entity_id),
                    link_kind="about",
                    status=status,
                    confidence=confidence,
                    evidence=evidence,
                    projector_version=projector_version,
                )
            if status == "approved":
                resolved_count += 1
            else:
                ambiguous_count += 1
    return {
        "resolved_count": resolved_count,
        "ambiguous_count": ambiguous_count,
        "unresolved_count": unresolved_count,
    }


def project_unit_entities_from_values(
    db: Session,
    *,
    tenant_id: UUID,
    unit_revision_id: UUID,
    values: Iterable[str],
    projector_version: str = "knowledge-authority-entity.v1",
) -> dict[str, int]:
    resolved_ids: list[str] = []
    ambiguous = unresolved = 0
    evidence: list[dict[str, Any]] = []
    for raw_value in values:
        value = str(raw_value or "").strip()
        if not value:
            continue
        resolution = resolve_entity(db, tenant_id=tenant_id, value=value)
        if resolution.status == "resolved":
            resolved_ids.extend(resolution.entity_ids)
            evidence.append({"kind": "published_applicability", "value": value})
        elif resolution.status == "ambiguous":
            ambiguous += 1
        else:
            unresolved += 1
    rows = project_unit_entity_links(
        db,
        tenant_id=tenant_id,
        unit_revision_id=unit_revision_id,
        entity_ids=resolved_ids,
        projector_version=projector_version,
        evidence=evidence,
    )
    return {
        "resolved_count": len(rows),
        "ambiguous_count": ambiguous,
        "unresolved_count": unresolved,
    }


def bounded_entity_ids(
    db: Session, *, tenant_id: UUID, seed_ids: Iterable[UUID]
) -> set[UUID]:
    seeds = set(seed_ids)
    if not seeds:
        return set()
    edges = (
        db.query(EntityRelationship)
        .filter(
            EntityRelationship.tenant_id == tenant_id,
            EntityRelationship.status == "approved",
            EntityRelationship.source_entity_id.in_(seeds),
        )
        .all()
    )
    # Exactly one hop; target entities are independently tenant-bound by FK/RLS.
    return seeds | {
        row.target_entity_id for row in edges if row.source_entity_id in seeds
    }


def expand_active_units_by_entity(
    db: Session, *, authz: AuthorizationContext, query: str, visible_units: list[Any]
) -> tuple[list[Any], dict[str, Any]]:
    resolution = resolve_entities_in_query(db, tenant_id=authz.tenant_id, query=query)
    if resolution["ambiguous_entity_ids"] or not resolution["resolved_entity_ids"]:
        return visible_units, resolution
    entity_ids = bounded_entity_ids(
        db, tenant_id=authz.tenant_id, seed_ids=resolution["resolved_entity_ids"]
    )
    visible_by_revision = {row.unit_revision_id: row for row in visible_units}
    links = (
        db.query(KnowledgeUnitEntityLink)
        .filter(
            KnowledgeUnitEntityLink.tenant_id == authz.tenant_id,
            KnowledgeUnitEntityLink.entity_id.in_(entity_ids),
            KnowledgeUnitEntityLink.status == "approved",
            KnowledgeUnitEntityLink.unit_revision_id.in_(visible_by_revision),
        )
        .all()
    )
    linked_ids = {row.unit_revision_id for row in links}
    return [
        (
            replace(
                row,
                metadata={
                    **row.metadata,
                    "entity_expanded": True,
                    "matched_entity_ids": [str(value) for value in entity_ids],
                },
            )
            if row.unit_revision_id in linked_ids
            else row
        )
        for row in visible_units
    ], resolution


def revoke_entity_projections(
    db: Session, *, tenant_id: UUID, asset_revision_id: UUID | None = None
) -> int:
    # Compatibility databases and N-1 test fixtures may not have received the
    # additive media-v2 migration yet. Cleanup must be harmless in that state.
    # Inspect through the Session's current connection. Inspecting the Engine can
    # borrow and roll back the same StaticPool connection used by SQLite tests.
    if not inspect(db.connection()).has_table(AssetEntityLink.__tablename__):
        return 0
    count = 0
    if asset_revision_id is not None:
        rows = (
            db.query(AssetEntityLink)
            .filter(
                AssetEntityLink.tenant_id == tenant_id,
                AssetEntityLink.asset_revision_id == asset_revision_id,
                AssetEntityLink.status.in_(("candidate", "approved")),
            )
            .all()
        )
        for row in rows:
            row.status = "revoked"
            count += 1
    return count
