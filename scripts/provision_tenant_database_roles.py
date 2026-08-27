#!/usr/bin/env python3
"""Provision least-privilege application and audited maintenance DB logins."""

from __future__ import annotations

import argparse
import json
import os

import psycopg2
from psycopg2 import sql


def _ensure_login_role(cur, role: str, password: str) -> None:
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
    identifier = sql.Identifier(role)
    statement = (
        "ALTER ROLE {} LOGIN PASSWORD %s INHERIT NOSUPERUSER NOCREATEDB "
        "NOCREATEROLE NOBYPASSRLS"
        if cur.fetchone()
        else "CREATE ROLE {} LOGIN PASSWORD %s INHERIT NOSUPERUSER NOCREATEDB "
        "NOCREATEROLE NOBYPASSRLS"
    )
    cur.execute(sql.SQL(statement).format(identifier), (password,))


def _grant_data_plane(cur, role: str, *, owner_role: str) -> None:
    identifier = sql.Identifier(role)
    owner = sql.Identifier(owner_role)
    cur.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(identifier))
    cur.execute(
        sql.SQL(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}"
        ).format(identifier)
    )
    cur.execute(
        sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}").format(
            identifier
        )
    )
    # Never auto-grant future tables to a login. A later migration may create
    # an append-only audit or another control-plane table. Deployments always
    # re-run this provisioner after migration, so only the reviewed current
    # schema receives data-plane grants.
    cur.execute(
        sql.SQL(
            "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public "
            "REVOKE ALL ON TABLES FROM {}"
        ).format(owner, identifier)
    )
    cur.execute(
        sql.SQL(
            "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public "
            "REVOKE ALL ON SEQUENCES FROM {}"
        ).format(owner, identifier)
    )


def provision(
    conn,
    *,
    application_role: str,
    application_password: str,
    maintenance_role: str,
    maintenance_password: str,
) -> dict[str, str]:
    if application_role == maintenance_role:
        raise ValueError("application and maintenance database roles must be distinct")
    if not application_password or not maintenance_password:
        raise ValueError("both database role passwords are required")

    owner_role = conn.info.user
    database_name = conn.info.dbname
    with conn.cursor() as cur:
        _ensure_login_role(cur, application_role, application_password)
        _ensure_login_role(cur, maintenance_role, maintenance_password)

        cur.execute(
            sql.SQL("GRANT enclave_application TO {}").format(
                sql.Identifier(application_role)
            )
        )
        cur.execute(
            sql.SQL("REVOKE enclave_rls_bypass FROM {}").format(
                sql.Identifier(application_role)
            )
        )
        cur.execute(
            sql.SQL("GRANT enclave_rls_bypass TO {}").format(
                sql.Identifier(maintenance_role)
            )
        )
        for role in (application_role, maintenance_role):
            cur.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(database_name), sql.Identifier(role)
                )
            )
            _grant_data_plane(cur, role, owner_role=owner_role)

        # Audit history is append-only and only the maintenance marker inherits
        # INSERT/sequence usage from the migration-created grants.
        for role in (application_role, maintenance_role):
            cur.execute(
                sql.SQL(
                    "REVOKE ALL ON TABLE platform_maintenance_audit FROM {}"
                ).format(sql.Identifier(role))
            )
            cur.execute(
                sql.SQL(
                    "REVOKE ALL ON SEQUENCE platform_maintenance_audit_id_seq FROM {}"
                ).format(sql.Identifier(role))
            )
        cur.execute(
            sql.SQL(
                "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public "
                "REVOKE ALL ON TABLES FROM enclave_rls_bypass"
            ).format(sql.Identifier(owner_role))
        )
    conn.commit()
    return {
        "status": "PASS",
        "database": database_name,
        "owner_role": owner_role,
        "application_role": application_role,
        "maintenance_role": maintenance_role,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--admin-dsn", default=os.getenv("DB_ADMIN_DSN"))
    parser.add_argument("--admin-host", default=os.getenv("DB_ADMIN_HOST"))
    parser.add_argument(
        "--admin-port", type=int, default=int(os.getenv("DB_ADMIN_PORT", "5432"))
    )
    parser.add_argument("--admin-database", default=os.getenv("DB_ADMIN_DATABASE"))
    parser.add_argument("--admin-user", default=os.getenv("DB_ADMIN_USER"))
    parser.add_argument("--admin-password", default=os.getenv("DB_ADMIN_PASSWORD"))
    parser.add_argument(
        "--application-role", default=os.getenv("POSTGRES_USER", "enclave_app")
    )
    parser.add_argument(
        "--application-password", default=os.getenv("POSTGRES_PASSWORD")
    )
    parser.add_argument(
        "--maintenance-role",
        default=os.getenv("MAINTENANCE_POSTGRES_USER", "enclave_maintenance"),
    )
    parser.add_argument(
        "--maintenance-password", default=os.getenv("MAINTENANCE_POSTGRES_PASSWORD")
    )
    args = parser.parse_args()
    if args.admin_dsn:
        connection_args = {"dsn": args.admin_dsn}
    else:
        missing = [
            name
            for name, value in (
                ("DB_ADMIN_HOST", args.admin_host),
                ("DB_ADMIN_DATABASE", args.admin_database),
                ("DB_ADMIN_USER", args.admin_user),
                ("DB_ADMIN_PASSWORD", args.admin_password),
            )
            if not value
        ]
        if missing:
            parser.error(
                "--admin-dsn/DB_ADMIN_DSN or discrete admin settings are required: "
                + ", ".join(missing)
            )
        connection_args = {
            "host": args.admin_host,
            "port": args.admin_port,
            "dbname": args.admin_database,
            "user": args.admin_user,
            "password": args.admin_password,
        }

    with psycopg2.connect(**connection_args) as conn:
        report = provision(
            conn,
            application_role=args.application_role,
            application_password=args.application_password or "",
            maintenance_role=args.maintenance_role,
            maintenance_password=args.maintenance_password or "",
        )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
