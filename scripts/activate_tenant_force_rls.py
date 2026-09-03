#!/usr/bin/env python3
"""Idempotently activate, disable, or verify FORCE RLS as the schema owner."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import psycopg2
from psycopg2 import sql


def _tables(cur) -> list[str]:
    cur.execute(
        """
        SELECT DISTINCT tablename
        FROM pg_catalog.pg_policies
        WHERE schemaname = 'public' AND policyname = 'tenant_isolation'
        ORDER BY tablename
        """
    )
    return [str(row[0]) for row in cur.fetchall()]


def set_force_rls(conn, *, operation: str) -> dict:
    with conn.cursor() as cur:
        tables = _tables(cur)
        if not tables:
            raise RuntimeError("no tenant_isolation policies found")
        if operation in {"activate", "disable"}:
            for table in tables:
                identifier = sql.Identifier("public", table)
                if operation == "activate":
                    cur.execute(
                        sql.SQL("ALTER TABLE {} ENABLE ROW LEVEL SECURITY").format(
                            identifier
                        )
                    )
                    cur.execute(
                        sql.SQL("ALTER TABLE {} FORCE ROW LEVEL SECURITY").format(
                            identifier
                        )
                    )
                else:
                    cur.execute(
                        sql.SQL("ALTER TABLE {} NO FORCE ROW LEVEL SECURITY").format(
                            identifier
                        )
                    )
        cur.execute(
            """
            SELECT count(DISTINCT p.tablename)::integer,
                   count(DISTINCT p.tablename) FILTER (
                     WHERE c.relrowsecurity
                   )::integer,
                   count(DISTINCT p.tablename) FILTER (
                     WHERE c.relforcerowsecurity
                   )::integer
            FROM pg_catalog.pg_policies p
            JOIN pg_catalog.pg_class c ON c.relname = p.tablename
            JOIN pg_catalog.pg_namespace n
              ON n.oid = c.relnamespace AND n.nspname = p.schemaname
            WHERE p.schemaname = 'public'
              AND p.policyname = 'tenant_isolation'
            """
        )
        protected, enabled, forced = (int(value or 0) for value in cur.fetchone())
    if operation in {"activate", "disable"}:
        conn.commit()
    expected_forced = protected if operation != "disable" else 0
    status = (
        "PASS"
        if protected > 0 and protected == enabled and forced == expected_forced
        else "FAIL"
    )
    return {
        "schema_version": "tenant-force-rls/v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "status": status,
        "operation": operation,
        "protected_table_count": protected,
        "enabled_table_count": enabled,
        "forced_table_count": forced,
        "errors": []
        if status == "PASS"
        else [
            "protected/enabled/forced counts do not match the requested RLS state"
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--admin-dsn", default=os.getenv("DB_ADMIN_DSN"))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--disable", action="store_true")
    parser.add_argument("--confirm", choices=("FORCE-RLS", "NO-FORCE-RLS"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.admin_dsn:
        parser.error("--admin-dsn or DB_ADMIN_DSN is required")
    if args.apply and args.confirm != "FORCE-RLS":
        parser.error("--apply requires --confirm FORCE-RLS")
    if args.disable and args.confirm != "NO-FORCE-RLS":
        parser.error("--disable requires --confirm NO-FORCE-RLS")
    operation = "activate" if args.apply else "disable" if args.disable else "verify"
    with psycopg2.connect(args.admin_dsn) as conn:
        report = set_force_rls(conn, operation=operation)
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["status"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
