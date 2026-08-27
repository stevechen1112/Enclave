#!/usr/bin/env python3
"""Machine gate for tenant-owned PostgreSQL tables and application DB roles."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extensions import connection as PgConnection

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "config" / "tenant_security_catalog.json"


@dataclass(frozen=True)
class ForeignKeyEdge:
    child_table: str
    child_column: str
    parent_table: str
    parent_column: str
    child_nullable: bool


def discover_inherited_tables(
    direct_tables: set[str],
    identity_tables: set[str],
    edges: Iterable[ForeignKeyEdge],
) -> dict[str, list[ForeignKeyEdge]]:
    """Return non-null FK descendants whose ownership is inherited recursively."""
    owned = set(direct_tables) | set(identity_tables)
    inherited: dict[str, list[ForeignKeyEdge]] = {}
    edge_list = list(edges)
    changed = True
    while changed:
        changed = False
        for edge in edge_list:
            if edge.child_nullable or edge.parent_table not in owned:
                continue
            if edge.child_table in owned:
                if edge.child_table in inherited:
                    inherited[edge.child_table].append(edge)
                continue
            owned.add(edge.child_table)
            inherited[edge.child_table] = [edge]
            changed = True
    return inherited


def _normalise_dsn(dsn: str) -> str:
    return dsn.replace("postgresql+psycopg2://", "postgresql://", 1)


def _fetch_all(
    conn: PgConnection, sql: str, params: tuple[Any, ...] = ()
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        columns = [desc.name for desc in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def _load_catalog(path: Path) -> dict[str, Any]:
    catalog = json.loads(path.read_text(encoding="utf-8"))
    if catalog.get("schema_version") != 1:
        raise ValueError("unsupported tenant security catalog schema")
    return catalog


def evaluate(
    conn: PgConnection,
    catalog: dict[str, Any],
    *,
    app_role: str | None,
    maintenance_role: str | None,
    require_force: bool,
) -> dict[str, Any]:
    errors: list[str] = []
    direct_rows = _fetch_all(
        conn,
        """
        SELECT table_name, is_nullable = 'YES' AS nullable
        FROM information_schema.columns
        WHERE table_schema = 'public' AND column_name = 'tenant_id'
        ORDER BY table_name
        """,
    )
    direct = {row["table_name"]: bool(row["nullable"]) for row in direct_rows}
    direct.pop("tenants", None)

    edge_rows = _fetch_all(
        conn,
        """
        SELECT tc.table_name AS child_table,
               kcu.column_name AS child_column,
               ccu.table_name AS parent_table,
               ccu.column_name AS parent_column,
               cols.is_nullable = 'YES' AS child_nullable
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage ccu
          ON ccu.constraint_name = tc.constraint_name
         AND ccu.table_schema = tc.table_schema
        JOIN information_schema.columns cols
          ON cols.table_schema = tc.table_schema
         AND cols.table_name = tc.table_name
         AND cols.column_name = kcu.column_name
        WHERE tc.constraint_type = 'FOREIGN KEY'
          AND tc.table_schema = 'public'
        ORDER BY tc.table_name, kcu.column_name
        """,
    )
    edges = [ForeignKeyEdge(**row) for row in edge_rows]
    identity = set(catalog["identity_tables"])
    discovered_inherited = discover_inherited_tables(set(direct), identity, edges)
    configured_inherited: dict[str, dict[str, str]] = catalog["inherited_tenant_tables"]

    missing_catalog = sorted(set(discovered_inherited) - set(configured_inherited))
    stale_catalog = sorted(set(configured_inherited) - set(discovered_inherited))
    if missing_catalog:
        errors.append(
            f"inherited tenant tables missing catalog decisions: {missing_catalog}"
        )
    if stale_catalog:
        errors.append(
            f"catalog inherited tables not discovered from non-null FK graph: {stale_catalog}"
        )

    for table, decision in configured_inherited.items():
        valid_edges = discovered_inherited.get(table, [])
        if not any(
            edge.parent_table == decision["parent_table"]
            and edge.child_column == decision["child_column"]
            and edge.parent_column == decision["parent_column"]
            for edge in valid_edges
        ):
            errors.append(f"catalog ownership edge no longer exists for {table}")

    nullable_decisions = set(catalog["nullable_global_read_tables"])
    actual_nullable = {table for table, nullable in direct.items() if nullable}
    if actual_nullable != nullable_decisions:
        errors.append(
            "nullable tenant table decisions differ: "
            f"missing={sorted(actual_nullable - nullable_decisions)}, "
            f"stale={sorted(nullable_decisions - actual_nullable)}"
        )

    protected = identity | set(direct) | set(configured_inherited)
    platform_global = set(catalog.get("platform_global_tables", []))
    table_rows = _fetch_all(
        conn,
        """
        SELECT c.relname AS table_name,
               c.relrowsecurity AS rls_enabled,
               c.relforcerowsecurity AS force_enabled
        FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind = 'r'
        ORDER BY c.relname
        """,
    )
    table_state = {row["table_name"]: row for row in table_rows}
    unclassified = (
        set(table_state)
        - protected
        - platform_global
        - {
            "alembic_version",
            "platform_maintenance_audit",
        }
    )
    if unclassified:
        errors.append(
            f"tables lack tenant or explicit platform-global decision: {sorted(unclassified)}"
        )
    missing_global = platform_global - set(table_state)
    if missing_global:
        errors.append(
            f"catalog platform-global tables do not exist: {sorted(missing_global)}"
        )

    policies = _fetch_all(
        conn,
        """
        SELECT tablename AS table_name, policyname, cmd, roles, qual, with_check
        FROM pg_catalog.pg_policies
        WHERE schemaname = 'public'
        ORDER BY tablename, policyname
        """,
    )
    by_table: dict[str, list[dict[str, Any]]] = {}
    for policy in policies:
        by_table.setdefault(policy["table_name"], []).append(policy)

    for table in sorted(protected):
        state = table_state.get(table)
        if not state:
            errors.append(f"catalog table does not exist: {table}")
            continue
        if not state["rls_enabled"]:
            errors.append(f"RLS disabled: {table}")
        if require_force and not state["force_enabled"]:
            errors.append(f"FORCE RLS disabled: {table}")
        table_policies = by_table.get(table, [])
        if (
            len(table_policies) != 1
            or table_policies[0]["policyname"] != "tenant_isolation"
        ):
            errors.append(f"{table} must have exactly one tenant_isolation policy")
            continue
        policy = table_policies[0]
        qual = str(policy.get("qual") or "")
        check = str(policy.get("with_check") or "")
        if (
            "app.tenant_id" not in qual
            or "app.bypass_rls" not in qual
            or "pg_has_role" not in qual
            or "enclave_rls_bypass" not in qual
        ):
            errors.append(f"{table} USING lacks tenant context or audited bypass")
        if (
            "app.tenant_id" not in check
            or "app.bypass_rls" not in check
            or "pg_has_role" not in check
            or "enclave_rls_bypass" not in check
        ):
            errors.append(f"{table} WITH CHECK lacks tenant context or audited bypass")
        if table in nullable_decisions:
            if "tenant_id IS NULL" not in qual:
                errors.append(f"{table} does not expose approved global rows for read")
            if "tenant_id IS NULL" in check:
                errors.append(f"{table} permits unaudited global-row writes")
        elif table in direct and "tenant_id IS NULL" in qual:
            errors.append(f"strict tenant table {table} permits global rows")
        if table in configured_inherited:
            parent = configured_inherited[table]["parent_table"]
            if parent not in qual or parent not in check:
                errors.append(f"{table} policy does not bind through parent {parent}")

    role_state: dict[str, Any] | None = None
    if app_role:
        rows = _fetch_all(
            conn,
            """
            SELECT rolname, rolcanlogin, rolsuper, rolbypassrls,
                   pg_has_role(rolname, 'enclave_application', 'member') AS application_member,
                   pg_has_role(rolname, 'enclave_rls_bypass', 'member') AS bypass_member,
                   has_function_privilege(
                       rolname,
                       'public.enclave_resolve_login_tenant(text)',
                       'EXECUTE'
                   ) AS can_resolve_login_tenant,
                   has_table_privilege(
                       rolname, 'public.platform_maintenance_audit', 'INSERT'
                   ) AS can_insert_maintenance_audit
            FROM pg_catalog.pg_roles WHERE rolname = %s
            """,
            (app_role,),
        )
        if not rows:
            errors.append(f"application role does not exist: {app_role}")
        else:
            role_state = rows[0]
            if not role_state["rolcanlogin"]:
                errors.append(f"application role cannot login: {app_role}")
            if role_state["rolsuper"]:
                errors.append(f"application role is superuser: {app_role}")
            if role_state["rolbypassrls"]:
                errors.append(f"application role has BYPASSRLS: {app_role}")
            if not role_state["application_member"]:
                errors.append(
                    f"application role lacks enclave_application membership: {app_role}"
                )
            if role_state["bypass_member"]:
                errors.append(f"application role is a tenant bypass member: {app_role}")
            if not role_state["can_resolve_login_tenant"]:
                errors.append(
                    f"application role cannot resolve login tenant: {app_role}"
                )
            if role_state["can_insert_maintenance_audit"]:
                errors.append(
                    f"application role can forge maintenance audit: {app_role}"
                )

    maintenance_state: dict[str, Any] | None = None
    if maintenance_role:
        rows = _fetch_all(
            conn,
            """
            SELECT rolname, rolcanlogin, rolsuper, rolbypassrls, rolinherit,
                   pg_has_role(rolname, 'enclave_rls_bypass', 'member') AS bypass_member,
                   has_table_privilege(
                       rolname, 'public.platform_maintenance_audit', 'INSERT'
                   ) AS can_insert_maintenance_audit,
                   has_table_privilege(
                       rolname, 'public.platform_maintenance_audit', 'UPDATE'
                   ) AS can_update_maintenance_audit,
                   has_table_privilege(
                       rolname, 'public.platform_maintenance_audit', 'DELETE'
                   ) AS can_delete_maintenance_audit
            FROM pg_catalog.pg_roles WHERE rolname = %s
            """,
            (maintenance_role,),
        )
        if not rows:
            errors.append(f"maintenance role does not exist: {maintenance_role}")
        else:
            maintenance_state = rows[0]
            if not maintenance_state["rolcanlogin"]:
                errors.append(f"maintenance role cannot login: {maintenance_role}")
            if maintenance_state["rolsuper"] or maintenance_state["rolbypassrls"]:
                errors.append(
                    f"maintenance role must not be superuser or native BYPASSRLS: {maintenance_role}"
                )
            if not maintenance_state["bypass_member"]:
                errors.append(
                    f"maintenance role lacks audited bypass membership: {maintenance_role}"
                )
            if not maintenance_state["rolinherit"]:
                errors.append(
                    f"maintenance role must inherit marker privileges: {maintenance_role}"
                )
            if not maintenance_state["can_insert_maintenance_audit"]:
                errors.append(
                    f"maintenance role cannot append bypass audit: {maintenance_role}"
                )
            if (
                maintenance_state["can_update_maintenance_audit"]
                or maintenance_state["can_delete_maintenance_audit"]
            ):
                errors.append(
                    f"maintenance role can mutate bypass audit history: {maintenance_role}"
                )

    return {
        "schema_version": 1,
        "gate": "TENANT-HARD-ISOLATION",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if not errors else "FAIL",
        "require_force_rls": require_force,
        "protected_table_count": len(protected),
        "direct_tenant_table_count": len(direct),
        "inherited_tenant_table_count": len(configured_inherited),
        "identity_table_count": len(identity),
        "nullable_global_read_table_count": len(nullable_decisions),
        "platform_global_table_count": len(platform_global),
        "application_role": role_state,
        "maintenance_role": maintenance_state,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dsn", default=os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
    )
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--app-role")
    parser.add_argument("--maintenance-role")
    parser.add_argument("--require-force", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.dsn:
        parser.error("--dsn, TEST_DATABASE_URL, or DATABASE_URL is required")

    catalog = _load_catalog(args.catalog)
    with psycopg2.connect(_normalise_dsn(args.dsn)) as conn:
        report = evaluate(
            conn,
            catalog,
            app_role=args.app_role,
            maintenance_role=args.maintenance_role,
            require_force=args.require_force,
        )
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
