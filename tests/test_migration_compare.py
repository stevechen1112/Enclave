from sqlalchemy import Column, Index, Integer, MetaData, String, Table, text

from app.db.migration_compare import (
    make_include_object,
    metadata_index_signature,
    reflected_index_signature,
)


def test_index_signatures_preserve_predicate_and_uniqueness():
    metadata = MetaData()
    table = Table("items", metadata, Column("tenant_id", String))
    index = Index(
        "uq_items_active",
        table.c.tenant_id,
        unique=True,
        postgresql_where=text("deleted_at IS NULL"),
    )

    assert metadata_index_signature(index) == (
        ("tenant_id",),
        True,
        "deleted_at is null",
        None,
    )
    assert reflected_index_signature(
        {
            "column_names": ["tenant_id"],
            "unique": True,
            "dialect_options": {"postgresql_where": "deleted_at IS NULL"},
        }
    ) == metadata_index_signature(index)


def test_include_object_ignores_name_only_drift_but_not_predicate_drift():
    metadata = MetaData()
    table = Table("items", metadata, Column("tenant_id", String))
    same = Index("ix_new_name", table.c.tenant_id)
    callback = make_include_object(
        {"items": {(('tenant_id',), False, None, None)}},
        {"items": {metadata_index_signature(same)}},
        {"items": frozenset()},
    )

    assert callback(same, same.name, "index", False, None) is False

    partial = Index(
        "uq_items_active",
        table.c.tenant_id,
        unique=True,
        postgresql_where=text("deleted_at IS NULL"),
    )
    assert callback(partial, partial.name, "index", False, None) is True


def test_include_object_ignores_redundant_primary_key_index():
    metadata = MetaData()
    table = Table("items", metadata, Column("id", Integer, primary_key=True))
    index = Index("ix_items_id", table.c.id)
    callback = make_include_object({}, {}, {"items": frozenset({"id"})})

    assert callback(index, index.name, "index", False, None) is False
