"""Tenant-scoped canonical entity and approved-alias resolution."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from uuid import UUID

from app.models.knowledge_engine import EntityAlias, EntityRegistry


def normalize_entity(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").casefold().strip()
    return re.sub(r"[\s\-_/（）()]+", "", value)


@dataclass(frozen=True)
class EntityResolution:
    status: str
    entity_ids: tuple[str, ...]


def resolve_entity(
    db, *, tenant_id, value: str, entity_type: str | None = None
) -> EntityResolution:
    normalized = normalize_entity(value)
    query = db.query(EntityRegistry).filter(
        EntityRegistry.tenant_id == tenant_id, EntityRegistry.status == "active"
    )
    if entity_type:
        query = query.filter(EntityRegistry.entity_type == entity_type)
    try:
        explicit_id = UUID(str(value))
    except (TypeError, ValueError):
        explicit_id = None
    if explicit_id is not None:
        explicit = query.filter(EntityRegistry.id == explicit_id).first()
        return (
            EntityResolution("resolved", (str(explicit.id),))
            if explicit is not None
            else EntityResolution("not_found", ())
        )
    direct = [
        entity
        for entity in query.all()
        if normalize_entity(entity.canonical_key) == normalized
        or normalize_entity(entity.display_name) == normalized
    ]
    aliases = (
        db.query(EntityAlias)
        .join(EntityRegistry, EntityAlias.entity_id == EntityRegistry.id)
        .filter(
            EntityAlias.tenant_id == tenant_id,
            EntityAlias.alias_normalized == normalized,
            EntityAlias.approved.is_(True),
            EntityRegistry.status == "active",
        )
    )
    if entity_type:
        aliases = aliases.filter(EntityRegistry.entity_type == entity_type)
    ids = {str(entity.id) for entity in direct}
    ids.update(str(alias.entity_id) for alias in aliases.all())
    if not ids:
        return EntityResolution("not_found", ())
    if len(ids) > 1:
        return EntityResolution("ambiguous", tuple(sorted(ids)))
    return EntityResolution("resolved", tuple(ids))


def add_alias(
    db,
    *,
    entity: EntityRegistry,
    alias: str,
    approved: bool,
    source_ref: dict | None = None,
) -> EntityAlias:
    normalized = normalize_entity(alias)
    if not normalized:
        raise ValueError("entity alias cannot be empty")
    row = EntityAlias(
        tenant_id=entity.tenant_id,
        entity_id=entity.id,
        alias=alias.strip(),
        alias_normalized=normalized,
        approved=approved,
        source_ref=source_ref or {},
    )
    db.add(row)
    db.flush()
    return row
