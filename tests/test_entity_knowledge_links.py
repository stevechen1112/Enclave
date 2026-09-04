from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.services.entity_knowledge_links import (
    bounded_entity_ids,
    project_asset_entities_from_metadata,
    resolve_entities_in_query,
)
from app.services.entity_registry import resolve_entity


class Query:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *args):
        return self

    def all(self):
        return self.rows


class DB:
    def __init__(self, entities, aliases=(), edges=()):
        self.entities, self.aliases, self.edges = entities, aliases, edges

    def query(self, model):
        name = getattr(model, "class_", model).__name__
        if name == "EntityRegistry":
            return Query(self.entities)
        if name == "EntityAlias":
            return Query(self.aliases)
        return Query(self.edges)


def test_approved_alias_resolves_equipment_in_natural_question():
    entity_id = uuid.uuid4()
    entity = SimpleNamespace(
        id=entity_id, canonical_key="equipment-a", display_name="A 型封口機"
    )
    alias = SimpleNamespace(entity_id=entity_id, alias="設備A")
    result = resolve_entities_in_query(
        DB([entity], [alias]), tenant_id=uuid.uuid4(), query="設備A如何復歸？"
    )
    assert result["resolved_entity_ids"] == (entity_id,)


def test_ambiguous_alias_never_auto_links():
    ids = [uuid.uuid4(), uuid.uuid4()]
    entities = [
        SimpleNamespace(
            id=value, canonical_key=str(value), display_name=f"機台 {index}"
        )
        for index, value in enumerate(ids)
    ]
    aliases = [SimpleNamespace(entity_id=value, alias="A機") for value in ids]
    result = resolve_entities_in_query(
        DB(entities, aliases), tenant_id=uuid.uuid4(), query="A機怎麼操作"
    )
    assert not result["resolved_entity_ids"]
    assert set(result["ambiguous_entity_ids"]) == set(ids)


def test_graph_expansion_is_exactly_one_hop():
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    db = DB(
        [],
        edges=[
            SimpleNamespace(source_entity_id=a, target_entity_id=b),
            SimpleNamespace(source_entity_id=b, target_entity_id=c),
        ],
    )
    assert bounded_entity_ids(db, tenant_id=uuid.uuid4(), seed_ids=[a]) == {a, b}


def test_asset_metadata_ambiguity_is_never_approved(monkeypatch):
    entity_ids = (str(uuid.uuid4()), str(uuid.uuid4()))
    writes = []
    monkeypatch.setattr(
        "app.services.entity_knowledge_links.resolve_entity",
        lambda *args, **kwargs: SimpleNamespace(
            status="ambiguous", entity_ids=entity_ids
        ),
    )
    monkeypatch.setattr(
        "app.services.entity_knowledge_links.project_asset_entity_link",
        lambda *args, **kwargs: writes.append(kwargs),
    )
    result = project_asset_entities_from_metadata(
        SimpleNamespace(),
        tenant_id=uuid.uuid4(),
        asset_revision_id=uuid.uuid4(),
        metadata={"equipment_ids": ["設備 A"]},
    )
    assert result["ambiguous_count"] == 1
    assert len(writes) == 2
    assert {row["status"] for row in writes} == {"candidate"}


def test_explicit_entity_uuid_is_tenant_scoped_and_resolved():
    entity_id = uuid.uuid4()

    class UUIDQuery:
        def filter(self, *args):
            return self

        def first(self):
            return SimpleNamespace(id=entity_id)

    class UUIDDB:
        def query(self, model):
            return UUIDQuery()

    result = resolve_entity(
        UUIDDB(), tenant_id=uuid.uuid4(), value=str(entity_id), entity_type="equipment"
    )
    assert result.status == "resolved"
    assert result.entity_ids == (str(entity_id),)
