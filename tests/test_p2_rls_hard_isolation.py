"""Production-like FORCE RLS attacks against real Enclave tables and DB roles."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse
from uuid import UUID, uuid4

import psycopg2
import pytest
from psycopg2 import errors
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.services.rls import apply_rls_bypass, apply_rls_context

ADMIN_DSN = os.getenv("P2_ADMIN_DSN")
APP_DSN = os.getenv("P2_APP_DSN")
MAINTENANCE_DSN = os.getenv("P2_MAINTENANCE_DSN")
MAINTENANCE_ROLE = urlparse(MAINTENANCE_DSN).username if MAINTENANCE_DSN else None
pytestmark = pytest.mark.skipif(
    not all((ADMIN_DSN, APP_DSN, MAINTENANCE_DSN)),
    reason="P2 FORCE-RLS database roles are not configured",
)


@dataclass(frozen=True)
class Seed:
    tenant_a: UUID
    tenant_b: UUID
    user_a: UUID
    user_b: UUID
    conversation_a: UUID
    conversation_b: UUID
    message_a: UUID
    message_b: UUID
    live_document_a: UUID
    tombstoned_document_a: UUID


@pytest.fixture(scope="module")
def seed() -> Seed:
    value = Seed(*(uuid4() for _ in range(10)))
    with psycopg2.connect(ADMIN_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO tenants (id, name, plan, status) VALUES (%s, 'P2 A', 'test', 'active'), (%s, 'P2 B', 'test', 'active')",
            (str(value.tenant_a), str(value.tenant_b)),
        )
        cur.execute(
            """
            INSERT INTO users (id, email, hashed_password, status, role, is_superuser, tenant_id)
            VALUES (%s, %s, 'hash', 'active', 'employee', false, %s),
                   (%s, %s, 'hash', 'active', 'employee', false, %s)
            """,
            (
                str(value.user_a),
                f"p2-a-{value.user_a}@example.invalid",
                str(value.tenant_a),
                str(value.user_b),
                f"p2-b-{value.user_b}@example.invalid",
                str(value.tenant_b),
            ),
        )
        cur.execute(
            "INSERT INTO departments (id, tenant_id, name) VALUES (%s, %s, 'A'), (%s, %s, 'B')",
            (str(uuid4()), str(value.tenant_a), str(uuid4()), str(value.tenant_b)),
        )
        cur.execute(
            "INSERT INTO conversations (id, tenant_id, user_id, title) VALUES (%s, %s, %s, 'A'), (%s, %s, %s, 'B')",
            (
                str(value.conversation_a),
                str(value.tenant_a),
                str(value.user_a),
                str(value.conversation_b),
                str(value.tenant_b),
                str(value.user_b),
            ),
        )
        cur.execute(
            "INSERT INTO messages (id, conversation_id, role, content) VALUES (%s, %s, 'user', 'A secret'), (%s, %s, 'user', 'B secret')",
            (
                str(value.message_a),
                str(value.conversation_a),
                str(value.message_b),
                str(value.conversation_b),
            ),
        )
        cur.execute(
            """
            INSERT INTO documents (id, tenant_id, filename, status, tombstoned_at)
            VALUES (%s, %s, 'live.txt', 'completed', NULL),
                   (%s, %s, 'revoked.txt', 'completed', now())
            """,
            (
                str(value.live_document_a),
                str(value.tenant_a),
                str(value.tombstoned_document_a),
                str(value.tenant_a),
            ),
        )
    yield value
    with psycopg2.connect(ADMIN_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM outbox_events WHERE tenant_id IN (%s, %s)",
            (str(value.tenant_a), str(value.tenant_b)),
        )
        cur.execute(
            "DELETE FROM platform_maintenance_audit WHERE metadata_json->>'test' = 'p2-hard-isolation'"
        )
        cur.execute(
            "DELETE FROM documents WHERE id IN (%s, %s)",
            (str(value.live_document_a), str(value.tombstoned_document_a)),
        )
        cur.execute(
            "DELETE FROM messages WHERE id IN (%s, %s)",
            (str(value.message_a), str(value.message_b)),
        )
        cur.execute(
            "DELETE FROM conversations WHERE id IN (%s, %s)",
            (str(value.conversation_a), str(value.conversation_b)),
        )
        cur.execute(
            "DELETE FROM departments WHERE tenant_id IN (%s, %s)",
            (str(value.tenant_a), str(value.tenant_b)),
        )
        cur.execute(
            "DELETE FROM users WHERE id IN (%s, %s)",
            (str(value.user_a), str(value.user_b)),
        )
        cur.execute(
            "DELETE FROM tenant_sidecar_bindings WHERE tenant_id IN (%s, %s)",
            (str(value.tenant_a), str(value.tenant_b)),
        )
        cur.execute(
            "DELETE FROM tenants WHERE id IN (%s, %s)",
            (str(value.tenant_a), str(value.tenant_b)),
        )


def _set_context(cur, tenant_id: UUID | None, *, bypass: bool = False) -> None:
    cur.execute(
        "SELECT set_config('app.tenant_id', %s, false)",
        (str(tenant_id) if tenant_id else "",),
    )
    cur.execute(
        "SELECT set_config('app.bypass_rls', %s, false)", ("on" if bypass else "off",)
    )


def test_missing_context_sees_no_direct_identity_or_inherited_rows(seed: Seed) -> None:
    with psycopg2.connect(APP_DSN) as conn, conn.cursor() as cur:
        _set_context(cur, None)
        for table in ("tenants", "departments", "messages"):
            cur.execute(f"SELECT count(*) FROM {table}")
            assert cur.fetchone()[0] == 0


def test_application_role_cannot_spoof_bypass_guc(seed: Seed) -> None:
    with psycopg2.connect(APP_DSN) as conn, conn.cursor() as cur:
        _set_context(cur, seed.tenant_a, bypass=True)
        cur.execute("SELECT id FROM tenants ORDER BY id")
        assert cur.fetchall() == [(str(seed.tenant_a),)]


def test_raw_sql_and_inherited_child_are_tenant_scoped(seed: Seed) -> None:
    with psycopg2.connect(APP_DSN) as conn, conn.cursor() as cur:
        _set_context(cur, seed.tenant_a)
        cur.execute("SELECT id FROM tenants")
        assert [row[0] for row in cur.fetchall()] == [str(seed.tenant_a)]
        cur.execute("SELECT content FROM messages")
        assert cur.fetchall() == [("A secret",)]
        cur.execute(
            "SELECT count(*) FROM departments WHERE tenant_id = %s",
            (str(seed.tenant_b),),
        )
        assert cur.fetchone()[0] == 0


def test_cross_tenant_direct_and_child_writes_are_blocked(seed: Seed) -> None:
    conn = psycopg2.connect(APP_DSN)
    try:
        cur = conn.cursor()
        _set_context(cur, seed.tenant_a)
        with pytest.raises(errors.InsufficientPrivilege):
            cur.execute(
                "INSERT INTO departments (id, tenant_id, name) VALUES (%s, %s, 'evil')",
                (str(uuid4()), str(seed.tenant_b)),
            )
        conn.rollback()
        cur = conn.cursor()
        _set_context(cur, seed.tenant_a)
        with pytest.raises(errors.InsufficientPrivilege):
            cur.execute(
                "INSERT INTO messages (id, conversation_id, role, content) VALUES (%s, %s, 'user', 'evil')",
                (str(uuid4()), str(seed.conversation_b)),
            )
    finally:
        conn.rollback()
        conn.close()


def test_idempotency_namespace_is_tenant_local(seed: Seed) -> None:
    shared_key = f"p2-shared-{uuid4()}"
    with psycopg2.connect(APP_DSN) as conn, conn.cursor() as cur:
        for tenant_id in (seed.tenant_a, seed.tenant_b):
            _set_context(cur, tenant_id)
            cur.execute(
                """
                INSERT INTO outbox_events (
                  tenant_id, aggregate_type, aggregate_id, event_type,
                  revision, payload, idempotency_key, status
                ) VALUES (%s, 'tenant', %s, 'updated', 1, %s, %s, 'pending')
                """,
                (
                    str(tenant_id),
                    str(tenant_id),
                    json.dumps({"tenant_id": str(tenant_id)}),
                    shared_key,
                ),
            )
            conn.commit()

        for tenant_id in (seed.tenant_a, seed.tenant_b):
            _set_context(cur, tenant_id)
            cur.execute(
                "SELECT tenant_id FROM outbox_events WHERE idempotency_key = %s",
                (shared_key,),
            )
            assert cur.fetchall() == [(str(tenant_id),)]


def test_login_resolver_returns_only_tenant_then_rls_protects_user(seed: Seed) -> None:
    email = f"p2-a-{seed.user_a}@example.invalid"
    with psycopg2.connect(APP_DSN) as conn, conn.cursor() as cur:
        cur.execute("SELECT public.enclave_resolve_login_tenant(%s)", (email,))
        assert cur.fetchone()[0] == str(seed.tenant_a)
        _set_context(cur, seed.tenant_a)
        cur.execute("SELECT id, tenant_id FROM users WHERE email = %s", (email,))
        assert cur.fetchone() == (str(seed.user_a), str(seed.tenant_a))


def test_sqlalchemy_context_survives_multiple_commits(seed: Seed) -> None:
    engine = create_engine(APP_DSN)
    factory = sessionmaker(bind=engine)
    db = factory()
    try:
        apply_rls_context(db, seed.tenant_a)
        for _ in range(3):
            rows = db.execute(text("SELECT tenant_id FROM departments")).fetchall()
            assert {row[0] for row in rows} == {seed.tenant_a}
            db.commit()
    finally:
        db.close()
        engine.dispose()


def test_stale_retrieval_cache_cannot_resurrect_tombstoned_document(seed: Seed) -> None:
    from app.services.kb_retrieval import KnowledgeBaseRetriever

    engine = create_engine(APP_DSN)
    factory = sessionmaker(bind=engine)
    retriever = KnowledgeBaseRetriever.__new__(KnowledgeBaseRetriever)
    retriever._redis = object()
    stale_results = [
        {
            "document_id": str(seed.live_document_a),
            "content": "live",
            "score": 1.0,
        },
        {
            "document_id": str(seed.tombstoned_document_a),
            "content": "must-not-resurrect",
            "score": 1.0,
        },
    ]
    try:
        with (
            patch("app.services.kb_retrieval.SessionLocal", factory),
            patch.object(retriever, "_cache_get", return_value=stale_results),
        ):
            results = retriever.search(
                seed.tenant_a,
                "cached query",
                use_cache=True,
                rerank=False,
            )
        assert [row["document_id"] for row in results] == [str(seed.live_document_a)]
    finally:
        engine.dispose()


def test_shadow_visibility_matches_explicit_tenant_ownership(seed: Seed) -> None:
    from scripts.rls_shadow_report import _catalog, evaluate

    root = Path(__file__).resolve().parents[1]
    with (
        psycopg2.connect(ADMIN_DSN) as admin_conn,
        psycopg2.connect(APP_DSN) as app_conn,
    ):
        report = evaluate(
            admin_conn,
            app_conn,
            _catalog(root / "config" / "tenant_security_catalog.json"),
            minimum_tenants=2,
        )
    assert report["status"] == "PASS", report
    # P2 established the 100-table floor; later product migrations add tenant
    # tables and must raise the verified count instead of making this stale.
    assert report["protected_table_count"] >= 100
    assert report["comparison_count"] >= 200
    assert report["difference_count"] == 0

    output = os.getenv("P2_SHADOW_REPORT_OUTPUT")
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def test_bypass_requires_independent_role_and_appends_immutable_audit(
    seed: Seed,
) -> None:
    app_engine = create_engine(APP_DSN)
    app_db = sessionmaker(bind=app_engine)()
    try:
        with pytest.raises(PermissionError):
            apply_rls_bypass(
                app_db,
                actor_identity="attacker",
                operation="spoof",
                reason="must be rejected",
            )
    finally:
        app_db.rollback()
        app_db.close()
        app_engine.dispose()

    maintenance_engine = create_engine(MAINTENANCE_DSN)
    maintenance_db = sessionmaker(bind=maintenance_engine)()
    try:
        apply_rls_bypass(
            maintenance_db,
            actor_identity="test:maintenance",
            operation="p2_attack_matrix",
            reason="verify independent audited maintenance access",
            metadata={"test": "p2-hard-isolation"},
        )
        assert (
            maintenance_db.execute(text("SELECT count(*) FROM tenants")).scalar() >= 2
        )
        maintenance_db.commit()
        assert (
            maintenance_db.execute(text("SELECT count(*) FROM tenants")).scalar() >= 2
        )
    finally:
        maintenance_db.close()
        maintenance_engine.dispose()

    with psycopg2.connect(ADMIN_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT db_role, actor_identity, operation, reason
            FROM platform_maintenance_audit
            WHERE metadata_json->>'test' = 'p2-hard-isolation'
            """
        )
        assert cur.fetchall() == [
            (
                MAINTENANCE_ROLE,
                "test:maintenance",
                "p2_attack_matrix",
                "verify independent audited maintenance access",
            )
        ]

    with (
        psycopg2.connect(MAINTENANCE_DSN) as conn,
        conn.cursor() as cur,
        pytest.raises(errors.InsufficientPrivilege),
    ):
        cur.execute(
            "UPDATE platform_maintenance_audit SET reason = 'forged' WHERE actor_identity = 'test:maintenance'"
        )


def test_future_control_plane_table_gets_no_login_default_grants(seed: Seed) -> None:
    table = f"p2_privilege_probe_{uuid4().hex}"
    try:
        with psycopg2.connect(ADMIN_DSN) as conn, conn.cursor() as cur:
            cur.execute(f'CREATE TABLE "{table}" (id integer primary key)')

        for dsn in (APP_DSN, MAINTENANCE_DSN):
            conn = psycopg2.connect(dsn)
            try:
                with conn.cursor() as cur, pytest.raises(errors.InsufficientPrivilege):
                    cur.execute(f'INSERT INTO "{table}" (id) VALUES (1)')
            finally:
                conn.rollback()
                conn.close()
    finally:
        with psycopg2.connect(ADMIN_DSN) as conn, conn.cursor() as cur:
            cur.execute(f'DROP TABLE IF EXISTS "{table}"')
