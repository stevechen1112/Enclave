"""Read-only Phase H PostgreSQL authority/RLS readiness report."""

from __future__ import annotations

import json
import os
import pathlib
import sys

from sqlalchemy import text

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from app.db.session import SessionLocal

TABLES = (
    "knowledge_units",
    "knowledge_unit_revisions",
    "knowledge_unit_releases",
    "knowledge_unit_release_memberships",
)


def main() -> int:
    db = SessionLocal()
    try:
        dialect = db.get_bind().dialect.name
        if dialect != "postgresql":
            print(json.dumps({"status": "blocked", "reason": "postgresql_required"}))
            return 2
        rows = db.execute(
            text(
                """
                SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
                       count(p.polname) AS policy_count
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                LEFT JOIN pg_policy p ON p.polrelid = c.oid
                WHERE n.nspname = 'public' AND c.relname = ANY(:tables)
                GROUP BY c.relname, c.relrowsecurity, c.relforcerowsecurity
                ORDER BY c.relname
                """
            ),
            {"tables": list(TABLES)},
        ).mappings().all()
        table_report = {
            row["relname"]: {
                "rls_enabled": row["relrowsecurity"],
                "force_rls": row["relforcerowsecurity"],
                "policy_count": row["policy_count"],
            }
            for row in rows
        }
        active_duplicates = db.execute(
            text(
                """
                SELECT tenant_id, release_key, count(*) AS count
                FROM knowledge_unit_releases
                WHERE status = 'active'
                GROUP BY tenant_id, release_key
                HAVING count(*) > 1
                """
            )
        ).mappings().all()
        schema_ready = set(table_report) == set(TABLES) and all(
            item["rls_enabled"] and item["policy_count"] >= 1
            for item in table_report.values()
        )
        report = {
            "status": "ready_for_shadow" if schema_ready and not active_duplicates else "fail",
            "tables": table_report,
            "duplicate_active_releases": [dict(row) for row in active_duplicates],
            "force_rls_enabled": all(
                item["force_rls"] for item in table_report.values()
            ),
            "production_cutover": {
                "status": "external_evidence_required",
                "minimum_shadow_days": 14,
                "requirements": [
                    "zero unexplained authority parity mismatches",
                    "non-superuser live tenant isolation suite passes",
                    "worker tenant context suite passes",
                    "rollback drill recorded",
                ],
            },
        }
        print(json.dumps(report, ensure_ascii=False, default=str, indent=2))
        return 0 if report["status"] == "ready_for_shadow" else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
