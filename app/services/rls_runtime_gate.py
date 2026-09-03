"""Fail-closed runtime preflight for enforced PostgreSQL tenant isolation."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


def evaluate_runtime_rls(db: Session) -> dict[str, Any]:
    if db.bind is None or db.bind.dialect.name != "postgresql":
        return {
            "status": "FAIL",
            "errors": ["RLS enforcement requires PostgreSQL"],
        }
    role = db.execute(
        text(
            """
            SELECT current_user AS rolname, r.rolsuper, r.rolbypassrls,
                   pg_has_role(current_user, 'enclave_application', 'member')
                     AS application_member,
                   pg_has_role(current_user, 'enclave_rls_bypass', 'member')
                     AS bypass_member
            FROM pg_catalog.pg_roles r
            WHERE r.rolname = current_user
            """
        )
    ).mappings().one()
    schema = db.execute(
        text(
            """
            SELECT count(DISTINCT p.tablename)::integer AS protected_table_count,
                   count(DISTINCT p.tablename) FILTER (
                     WHERE c.relrowsecurity
                   )::integer AS enabled_table_count,
                   count(DISTINCT p.tablename) FILTER (
                     WHERE c.relforcerowsecurity
                   )::integer AS forced_table_count
            FROM pg_catalog.pg_policies p
            JOIN pg_catalog.pg_class c ON c.relname = p.tablename
            JOIN pg_catalog.pg_namespace n
              ON n.oid = c.relnamespace AND n.nspname = p.schemaname
            WHERE p.schemaname = 'public'
              AND p.policyname = 'tenant_isolation'
            """
        )
    ).mappings().one()
    errors: list[str] = []
    if role["rolsuper"]:
        errors.append("application database role is superuser")
    if role["rolbypassrls"]:
        errors.append("application database role has BYPASSRLS")
    if not role["application_member"]:
        errors.append("application database role lacks enclave_application membership")
    if role["bypass_member"]:
        errors.append("application database role is an RLS bypass member")
    protected = int(schema["protected_table_count"] or 0)
    enabled = int(schema["enabled_table_count"] or 0)
    forced = int(schema["forced_table_count"] or 0)
    if protected == 0:
        errors.append("no tenant isolation policies are installed")
    if enabled != protected:
        errors.append(f"RLS is not enabled on every protected table ({enabled}/{protected})")
    if forced != protected:
        errors.append(f"FORCE RLS is not active on every protected table ({forced}/{protected})")
    return {
        "status": "PASS" if not errors else "FAIL",
        "role": dict(role),
        "protected_table_count": protected,
        "enabled_table_count": enabled,
        "forced_table_count": forced,
        "errors": errors,
    }


def assert_runtime_rls_ready() -> dict[str, Any]:
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        report = evaluate_runtime_rls(db)
    finally:
        db.close()
    if report["status"] != "PASS":
        raise RuntimeError("tenant RLS runtime gate failed: " + "; ".join(report["errors"]))
    return report
