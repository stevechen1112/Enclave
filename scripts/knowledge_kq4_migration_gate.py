"""Exercise the KQ4 migration on an isolated PostgreSQL database."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.migrations.versions import (  # noqa: E402
    knowledge_typed_relation_kq4_001 as migration,
)


def _run(connection: sa.Connection, operation: str) -> None:
    context = MigrationContext.configure(connection)
    migration.op = Operations(context)
    getattr(migration, operation)()


def _scalar(connection: sa.Connection, statement: str) -> Any:
    return connection.execute(sa.text(statement)).scalar()


def main() -> int:
    database_url = os.environ["KQ4_GATE_DATABASE_URL"]
    os.environ["RLS_ENFORCEMENT_ENABLED"] = "true"
    engine = sa.create_engine(database_url)
    report: dict[str, Any] = {}
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                CREATE TABLE tenants (id uuid PRIMARY KEY);
                CREATE TABLE users (id uuid PRIMARY KEY);
                CREATE TABLE evidence_spans (id uuid PRIMARY KEY);
                CREATE TABLE knowledge_units (
                    id uuid PRIMARY KEY,
                    unit_type varchar(32) NOT NULL,
                    CONSTRAINT ck_knowledge_units_type CHECK (
                        unit_type IN ('narrative','row','field','procedure',
                        'knowhow','entity','compiled')
                    )
                );
                CREATE TABLE knowledge_unit_revisions (
                    id uuid PRIMARY KEY,
                    tenant_id uuid NOT NULL REFERENCES tenants(id),
                    UNIQUE (tenant_id, id)
                );
                """
            )
        )
        _run(connection, "upgrade")
        report["upgrade"] = bool(
            _scalar(
                connection,
                """SELECT 1 FROM information_schema.tables
                WHERE table_name = 'knowledge_unit_relation_projections'""",
            )
        )
        report["section_path"] = bool(
            _scalar(
                connection,
                """SELECT 1 FROM information_schema.columns
                WHERE table_name = 'evidence_spans' AND column_name = 'section_path'""",
            )
        )
        report["rls_forced"] = bool(
            _scalar(
                connection,
                """SELECT relforcerowsecurity FROM pg_class
                WHERE relname = 'knowledge_unit_relation_projections'""",
            )
        )
        report["tenant_policy"] = bool(
            _scalar(
                connection,
                """SELECT 1 FROM pg_policies
                WHERE tablename = 'knowledge_unit_relation_projections'
                  AND policyname = 'tenant_isolation'""",
            )
        )
        _run(connection, "downgrade")
        report["downgrade"] = not bool(
            _scalar(
                connection,
                """SELECT 1 FROM information_schema.tables
                WHERE table_name = 'knowledge_unit_relation_projections'""",
            )
        )
        report["downgrade_section_path_removed"] = not bool(
            _scalar(
                connection,
                """SELECT 1 FROM information_schema.columns
                WHERE table_name = 'evidence_spans' AND column_name = 'section_path'""",
            )
        )
        _run(connection, "upgrade")
        report["forward_recovery"] = bool(
            _scalar(
                connection,
                """SELECT 1 FROM information_schema.tables
                WHERE table_name = 'knowledge_unit_relation_projections'""",
            )
        )
    engine.dispose()
    report["status"] = "pass" if all(report.values()) else "fail"
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
