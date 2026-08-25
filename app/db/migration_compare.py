"""Semantic filters used by Alembic autogenerate.

Historical migrations used several index naming conventions.  Alembic normally
matches indexes by name, which makes a harmless rename look like a drop/create.
This module suppresses only two classes of non-schema drift:

* an index whose columns, uniqueness and PostgreSQL predicate already exist;
* an index containing only primary-key columns (the PK already owns an index).

Constraints, foreign keys, nullability, predicates and genuinely different
index definitions remain visible to ``alembic check``.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.schema import Index, MetaData

IndexSignature = tuple[tuple[str, ...], bool, str | None, bool | None]


def _normalise_predicate(value: Any) -> str | None:
    if value is None:
        return None
    rendered = re.sub(r"\s+", " ", str(value)).strip().lower()
    return rendered or None


def metadata_index_signature(index: Index) -> IndexSignature:
    columns = tuple(
        str(getattr(expression, "name", None) or expression)
        for expression in index.expressions
    )
    predicate = index.dialect_options["postgresql"].get("where")
    nulls_not_distinct = index.dialect_options["postgresql"].get("nulls_not_distinct")
    return columns, bool(index.unique), _normalise_predicate(predicate), nulls_not_distinct


def reflected_index_signature(index: Mapping[str, Any]) -> IndexSignature:
    dialect_options = index.get("dialect_options") or {}
    predicate = dialect_options.get("postgresql_where") or index.get("postgresql_where")
    nulls_not_distinct = dialect_options.get("postgresql_nulls_not_distinct")
    return (
        tuple(str(column) for column in (index.get("column_names") or ())),
        bool(index.get("unique")),
        _normalise_predicate(predicate),
        nulls_not_distinct,
    )


def collect_index_signatures(connection, metadata: MetaData):
    """Return reflected/declared signatures plus each table's PK columns."""
    inspector = inspect(connection)
    reflected: dict[str, set[IndexSignature]] = {}
    for table_name in inspector.get_table_names():
        reflected[table_name] = {
            reflected_index_signature(item)
            for item in inspector.get_indexes(table_name)
        }

    declared: dict[str, set[IndexSignature]] = {}
    primary_keys: dict[str, frozenset[str]] = {}
    for table_name, table in metadata.tables.items():
        declared[table_name] = {metadata_index_signature(item) for item in table.indexes}
        primary_keys[table_name] = frozenset(column.name for column in table.primary_key.columns)
    return reflected, declared, primary_keys


def make_include_object(
    reflected: Mapping[str, set[IndexSignature]],
    declared: Mapping[str, set[IndexSignature]],
    primary_keys: Mapping[str, frozenset[str]],
):
    """Build an Alembic ``include_object`` callback with fail-open defaults."""

    def include_object(obj, _name, type_, is_reflected, _compare_to) -> bool:
        if type_ != "index":
            return True

        table_name = obj.table.name
        if is_reflected:
            signature = reflected_index_signature(
                {
                    "column_names": [column.name for column in obj.columns],
                    "unique": obj.unique,
                    "dialect_options": {
                        "postgresql_where": obj.dialect_options["postgresql"].get("where")
                    },
                }
            )
            counterpart = declared.get(table_name, set())
        else:
            signature = metadata_index_signature(obj)
            counterpart = reflected.get(table_name, set())

        columns = frozenset(signature[0])
        if columns and columns.issubset(primary_keys.get(table_name, frozenset())):
            return False
        return signature not in counterpart

    return include_object
