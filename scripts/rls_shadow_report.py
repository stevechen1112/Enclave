#!/usr/bin/env python3
"""Compare explicit tenant ownership with rows visible to the application role."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extensions import connection as PgConnection

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "config" / "tenant_security_catalog.json"
_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")


def _ident(value: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"unsafe SQL identifier: {value!r}")
    return f'"{value}"'


def _normalise_dsn(dsn: str) -> str:
    return dsn.replace("postgresql+psycopg2://", "postgresql://", 1)


def _catalog(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != 1:
        raise ValueError("unsupported tenant security catalog schema")
    return value


def _direct_tables(conn: PgConnection) -> dict[str, bool]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name, is_nullable = 'YES'
            FROM information_schema.columns
            WHERE table_schema = 'public' AND column_name = 'tenant_id'
            ORDER BY table_name
            """
        )
        return {str(table): bool(nullable) for table, nullable in cur.fetchall()}


def _expected_count_sql(
    table: str,
    *,
    direct: dict[str, bool],
    identity: dict[str, dict[str, str]],
    inherited: dict[str, dict[str, str]],
) -> str:
    table_sql = _ident(table)
    if table in identity:
        column = _ident(identity[table]["tenant_identity_column"])
        return f"SELECT count(*) FROM {table_sql} WHERE {column} = %s"
    if table in direct:
        predicate = '"tenant_id" = %s'
        if direct[table]:
            predicate = f'("tenant_id" IS NULL OR {predicate})'
        return f"SELECT count(*) FROM {table_sql} WHERE {predicate}"

    joins: list[str] = []
    current = table
    current_alias = "t0"
    depth = 0
    while current in inherited:
        decision = inherited[current]
        depth += 1
        parent_alias = f"t{depth}"
        joins.append(
            f"JOIN {_ident(decision['parent_table'])} {parent_alias} "
            f"ON {parent_alias}.{_ident(decision['parent_column'])} = "
            f"{current_alias}.{_ident(decision['child_column'])}"
        )
        current = decision["parent_table"]
        current_alias = parent_alias
    if current in direct:
        root_predicate = f'{current_alias}."tenant_id" = %s'
    elif current in identity:
        root_column = _ident(identity[current]["tenant_identity_column"])
        root_predicate = f"{current_alias}.{root_column} = %s"
    else:
        raise ValueError(f"inherited ownership for {table} has no tenant root")
    return (
        f"SELECT count(*) FROM {table_sql} t0 {' '.join(joins)} WHERE {root_predicate}"
    )


def evaluate(
    admin_conn: PgConnection,
    app_conn: PgConnection,
    catalog: dict[str, Any],
    *,
    minimum_tenants: int = 1,
) -> dict[str, Any]:
    direct = _direct_tables(admin_conn)
    identity = catalog["identity_tables"]
    inherited = catalog["inherited_tenant_tables"]
    protected = sorted(set(direct) | set(identity) | set(inherited))
    errors: list[str] = []
    comparisons: list[dict[str, Any]] = []

    with admin_conn.cursor() as cur:
        cur.execute("SELECT id FROM tenants ORDER BY id")
        tenant_ids = [str(row[0]) for row in cur.fetchall()]
    if len(tenant_ids) < minimum_tenants:
        errors.append(
            f"shadow report requires at least {minimum_tenants} tenants; "
            f"found {len(tenant_ids)}"
        )

    for tenant_id in tenant_ids:
        with app_conn.cursor() as app_cur:
            app_cur.execute(
                "SELECT set_config('app.bypass_rls', 'off', false), "
                "set_config('app.tenant_id', %s, false)",
                (tenant_id,),
            )
        for table in protected:
            try:
                expected_sql = _expected_count_sql(
                    table,
                    direct=direct,
                    identity=identity,
                    inherited=inherited,
                )
                with admin_conn.cursor() as admin_cur:
                    admin_cur.execute(expected_sql, (tenant_id,))
                    expected = int(admin_cur.fetchone()[0])
                with app_conn.cursor() as app_cur:
                    app_cur.execute(f"SELECT count(*) FROM {_ident(table)}")
                    observed = int(app_cur.fetchone()[0])
                comparisons.append(
                    {
                        "tenant_id": tenant_id,
                        "table": table,
                        "expected_rows": expected,
                        "application_visible_rows": observed,
                        "difference": observed - expected,
                    }
                )
            except Exception as exc:  # noqa: BLE001 - report every per-table gate failure
                admin_conn.rollback()
                app_conn.rollback()
                errors.append(f"{tenant_id}/{table}: {type(exc).__name__}: {exc}")
                break

    differences = [row for row in comparisons if row["difference"] != 0]
    return {
        "schema_version": 1,
        "gate": "RLS-SHADOW-DIFFERENCE",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if not errors and not differences else "FAIL",
        "tenant_count": len(tenant_ids),
        "protected_table_count": len(protected),
        "comparison_count": len(comparisons),
        "difference_count": len(differences),
        "differences": differences,
        "comparisons": comparisons,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--admin-dsn", default=os.getenv("P2_ADMIN_DSN"))
    parser.add_argument("--app-dsn", default=os.getenv("P2_APP_DSN"))
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--minimum-tenants", type=int, default=1)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.admin_dsn or not args.app_dsn:
        parser.error("--admin-dsn/P2_ADMIN_DSN and --app-dsn/P2_APP_DSN are required")

    with (
        psycopg2.connect(_normalise_dsn(args.admin_dsn)) as admin_conn,
        psycopg2.connect(_normalise_dsn(args.app_dsn)) as app_conn,
    ):
        report = evaluate(
            admin_conn,
            app_conn,
            _catalog(args.catalog),
            minimum_tenants=args.minimum_tenants,
        )
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
