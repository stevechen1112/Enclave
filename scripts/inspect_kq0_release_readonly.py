#!/usr/bin/env python3
"""Emit a privacy-preserving KQ0 release identity from a read-only runtime.

The probe deliberately avoids source text and tenant/user identifiers.  It is
compatible with older production images: missing post-K0 tables are reported
as absent instead of turning a read-only evidence capture into a deployment.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any

from sqlalchemy import inspect, text

from app.composition.packs import build_pack_registry
from app.db.session import SessionLocal


TABLES = (
    "documents",
    "documentchunks",
    "knowledge_bases",
    "knowledge_base_revisions",
    "knowledge_base_revision_documents",
    "knowledge_units",
    "knowledge_unit_revisions",
    "knowledge_unit_releases",
    "knowledge_unit_release_memberships",
    "source_acl_entries",
)


def _digest(values: Iterable[Any]) -> str:
    material = "\n".join(sorted(str(value) for value in values))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _pseudonym(value: Any) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]


def _rows(db, statement: str) -> list[tuple[Any, ...]]:
    return [tuple(row) for row in db.execute(text(statement)).all()]


def _table_sentinel(db, inspector, table: str) -> dict[str, Any]:
    columns = {column["name"] for column in inspector.get_columns(table)}
    selected = [
        name
        for name in (
            "id",
            "tenant_id",
            "status",
            "revision",
            "content_hash",
            "manifest_hash",
            "policy_revision",
            "quality_state",
            "updated_at",
            "tombstoned_at",
        )
        if name in columns
    ]
    if not selected:
        return {"count": 0, "digest": _digest(())}
    quoted = ", ".join(f'"{name}"' for name in selected)
    rows = _rows(db, f'SELECT {quoted} FROM "{table}"')
    return {"count": len(rows), "digest": _digest(rows)}


def _pack_versions() -> list[dict[str, Any]]:
    registry = build_pack_registry()
    versions: list[dict[str, Any]] = []
    for key in registry.pack_keys:
        contribution = registry.get(key)
        if contribution is None:
            continue
        versions.append(
            {
                "pack_key": key,
                "pack_version": contribution.manifest.pack_version,
                "deployed": registry.is_deployed(key),
            }
        )
    return versions


def main() -> int:
    db = SessionLocal()
    try:
        db.execute(text("SET TRANSACTION READ ONLY"))
        inspector = inspect(db.bind)
        present = set(inspector.get_table_names())
        sentinels = {
            table: _table_sentinel(db, inspector, table)
            for table in TABLES
            if table in present
        }

        kb_revisions: list[dict[str, Any]] = []
        if {"knowledge_bases", "knowledge_base_revisions"}.issubset(present):
            for row in _rows(
                db,
                """
                SELECT kb.tenant_id, kb.id, kb.active_revision, r.id, r.revision,
                       r.status, COALESCE(r.manifest_hash, ''), r.policy_revision
                FROM knowledge_bases kb
                LEFT JOIN knowledge_base_revisions r
                  ON r.kb_id = kb.id AND r.revision = kb.active_revision
                WHERE kb.status = 'active'
                ORDER BY kb.tenant_id, kb.id
                """,
            ):
                kb_revisions.append(
                    {
                        "tenant_ref": _pseudonym(row[0]),
                        "kb_id": str(row[1]),
                        "active_revision_number": row[2],
                        "revision_id": str(row[3]) if row[3] else None,
                        "revision": row[4],
                        "status": row[5],
                        "manifest_hash": row[6],
                        "policy_revision": row[7],
                    }
                )

        unit_releases: list[dict[str, Any]] = []
        if "knowledge_unit_releases" in present:
            membership_join = ""
            if "knowledge_unit_release_memberships" in present:
                membership_join = """
                    LEFT JOIN knowledge_unit_release_memberships m
                      ON m.tenant_id = r.tenant_id AND m.release_id = r.id
                     AND m.status = 'active'
                """
            for row in _rows(
                db,
                f"""
                SELECT r.tenant_id, r.id, r.release_key, r.revision,
                       r.scope_kind, r.scope_id, r.scope_revision_id, r.status,
                       r.policy_revision, COALESCE(r.manifest_hash, ''),
                       count(m.id) AS active_memberships
                FROM knowledge_unit_releases r
                {membership_join}
                WHERE r.status = 'active'
                GROUP BY r.tenant_id, r.id, r.release_key, r.revision,
                         r.scope_kind, r.scope_id, r.scope_revision_id, r.status,
                         r.policy_revision, r.manifest_hash
                ORDER BY r.tenant_id, r.release_key
                """,
            ):
                unit_releases.append(
                    {
                        "tenant_ref": _pseudonym(row[0]),
                        "release_id": str(row[1]),
                        "release_key": row[2],
                        "revision": row[3],
                        "scope_kind": row[4],
                        "scope_id": str(row[5]) if row[5] else None,
                        "scope_revision_id": str(row[6]) if row[6] else None,
                        "status": row[7],
                        "policy_revision": row[8],
                        "manifest_hash": row[9],
                        "active_memberships": row[10],
                    }
                )

        payload = {
            "schema_version": "kq0-release-snapshot.v1",
            "privacy": "metadata_counts_digests_and_pseudonymous_tenants_only",
            "transaction_read_only": db.execute(
                text("SHOW transaction_read_only")
            ).scalar()
            == "on",
            "tables_present": sorted(set(TABLES).intersection(present)),
            "table_sentinels": sentinels,
            "active_kb_revisions": kb_revisions,
            "active_knowledge_unit_releases": unit_releases,
            "pack_versions": _pack_versions(),
        }
        payload["snapshot_digest"] = _digest(
            (json.dumps(payload, sort_keys=True, default=str),)
        )
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))
        db.rollback()
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
