"""tenant_sidecar_binding 隔離測試（ADR-013）。

涵蓋：fail-closed 解析、ensure_binding 冪等、pack 未啟用語意、
outbox worker 不再讀全域環境變數、router 注入 binding KB、
控制面程式不得直接讀 sidecar 歸屬環境變數（靜態掃描）、
live PG 種子完整性。
"""
import os
import sys
import types
import unittest
import uuid
from typing import ClassVar
from unittest.mock import MagicMock, patch

sys.path.insert(0, ".")

from app.services.sidecar_binding import (
    SidecarBindingError,
    ensure_binding,
    get_binding,
    resolve_ragflow_dataset_id,
    resolve_weknora_kb_id,
)

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()


def _db_with_binding(binding):
    """回傳查詢結果固定為 binding 的假 db session。"""
    db = MagicMock()
    query = db.query.return_value
    query.filter.return_value.first.return_value = binding
    return db


def _binding(tenant_id, dataset=None, kb=None):
    return types.SimpleNamespace(
        tenant_id=tenant_id,
        ragflow_dataset_id=dataset,
        weknora_kb_id=kb,
        pipeshub_org_id=None,
        credentials_ref=None,
    )


class TestGetBinding(unittest.TestCase):
    def test_missing_binding_raises(self):
        db = _db_with_binding(None)
        with self.assertRaises(SidecarBindingError):
            get_binding(db, TENANT_A)

    def test_existing_binding_returned(self):
        b = _binding(TENANT_A, dataset="ds-a")
        self.assertIs(get_binding(_db_with_binding(b), TENANT_A), b)

    def test_resolve_returns_ids(self):
        b = _binding(TENANT_A, dataset="ds-a", kb="kb-a")
        db = _db_with_binding(b)
        self.assertEqual(resolve_ragflow_dataset_id(db, TENANT_A), "ds-a")
        self.assertEqual(resolve_weknora_kb_id(db, TENANT_A), "kb-a")

    def test_pack_not_enabled_returns_none(self):
        # NULL 欄位＝pack 未啟用（合法狀態），與 binding 缺失（隔離破口）不同
        b = _binding(TENANT_A, dataset=None, kb=None)
        db = _db_with_binding(b)
        self.assertIsNone(resolve_ragflow_dataset_id(db, TENANT_A))
        self.assertIsNone(resolve_weknora_kb_id(db, TENANT_A))

    def test_two_tenants_isolated(self):
        # 同名查詢依 tenant_id 過濾——模擬兩租戶各自解析到各自歸屬
        b_a = _binding(TENANT_A, dataset="ds-a")
        b_b = _binding(TENANT_B, dataset="ds-b")
        self.assertEqual(
            resolve_ragflow_dataset_id(_db_with_binding(b_a), TENANT_A), "ds-a"
        )
        self.assertEqual(
            resolve_ragflow_dataset_id(_db_with_binding(b_b), TENANT_B), "ds-b"
        )
        self.assertNotEqual(
            resolve_ragflow_dataset_id(_db_with_binding(b_a), TENANT_A),
            resolve_ragflow_dataset_id(_db_with_binding(b_b), TENANT_B),
        )


class TestEnsureBinding(unittest.TestCase):
    def test_creates_when_missing(self):
        db = _db_with_binding(None)
        ensure_binding(db, TENANT_A)
        db.add.assert_called_once()
        db.flush.assert_called_once()

    def test_idempotent_when_exists(self):
        b = _binding(TENANT_A)
        db = _db_with_binding(b)
        self.assertIs(ensure_binding(db, TENANT_A), b)
        db.add.assert_not_called()


class TestOutboxWorkerResolution(unittest.TestCase):
    """outbox worker：payload 缺 sidecar ID 時走 binding，不讀全域環境變數。"""

    def test_env_vars_not_consulted(self):
        # 靜態驗證：outbox_worker 的 ingest 準備段不再有 RAGFLOW_DATASET_ID fallback
        import inspect

        from app.tasks import outbox_worker

        src = inspect.getsource(outbox_worker)
        self.assertNotIn('os.getenv("RAGFLOW_DATASET_ID"', src)
        self.assertNotIn('os.getenv("WEKNORA_DEFAULT_KB_ID"', src)


class TestRouterScopeInjection(unittest.TestCase):
    """router.search：db 可用且 scope 未指定時，注入 binding 的 KB。"""

    def test_injects_binding_kb_into_scope(self):
        import asyncio

        from app.gateway.router import GatewayRouter

        router = GatewayRouter.__new__(GatewayRouter)
        router.authorizer = MagicMock()
        router._adapters = {}  # 無 adapter → 注入後走 no_adapter 分支提早返回
        decision = MagicMock()
        decision.allowed = True
        decision.matched_rules = []
        router.authorizer.authorize_search.return_value = decision

        captured = {}

        def fake_resolve(db, tenant_id):
            captured["tenant_id"] = tenant_id
            return "kb-from-binding"

        authz = types.SimpleNamespace(tenant_id=TENANT_A)
        with patch(
            "app.services.sidecar_binding.resolve_weknora_kb_id", fake_resolve
        ):
            asyncio.run(
                router.search(
                    authz=authz, query="q", domain=MagicMock(value="wiki"),
                    top_k=5, scope=None, db=MagicMock(),
                )
            )
        self.assertEqual(captured.get("tenant_id"), TENANT_A)


class TestControlPlaneEnvScan(unittest.TestCase):
    """靜態掃描：控制面（services/tasks/api）不得直接讀 sidecar 歸屬環境變數。

    允許清單：sidecar_binding.py 的 legacy_* 部署級預設 helper、
    parse_pipeline 的無租戶上下文（測試／維運）fallback。
    """

    _PATTERNS = ('os.getenv("RAGFLOW_DATASET_ID"', "os.getenv('RAGFLOW_DATASET_ID'",
                 'os.getenv("WEKNORA_KB_ID"', "os.getenv('WEKNORA_KB_ID'",
                 'os.getenv("WEKNORA_DEFAULT_KB_ID"', "os.getenv('WEKNORA_DEFAULT_KB_ID'")
    _ALLOWED: ClassVar[set[str]] = {
        os.path.join("app", "services", "sidecar_binding.py"),
        os.path.join("app", "services", "parse_pipeline.py"),
    }

    def test_no_control_plane_env_reads(self):
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[1]
        violations = []
        for sub in ("services", "tasks", os.path.join("api")):
            for py in (root / "app" / sub).rglob("*.py"):
                rel = str(py.relative_to(root))
                if rel in self._ALLOWED:
                    continue
                text = py.read_text(encoding="utf-8")
                for pat in self._PATTERNS:
                    if pat in text:
                        violations.append(f"{rel}: {pat}")
        self.assertEqual(violations, [], "控制面直接讀 sidecar 歸屬環境變數")


# ---------------------------------------------------------------------------
# Live PG：種子完整性（每個租戶都有 binding 且帶部署級歸屬）
# ---------------------------------------------------------------------------

PG_DSN = os.environ.get(
    "ENCLAVE_TEST_PG_DSN",
    "postgresql://postgres:postgres@localhost:5435/enclave",
)


def _pg_available() -> bool:
    import psycopg2

    try:
        conn = psycopg2.connect(PG_DSN, connect_timeout=3)
        conn.close()
        return True
    except psycopg2.Error:
        return False


@unittest.skipUnless(_pg_available(), "live PostgreSQL unavailable")
class TestLiveBindingSeed(unittest.TestCase):
    def test_every_tenant_has_binding(self):
        """隔離不變量：任何租戶都不得缺 binding（缺 binding＝隔離破口）。"""
        import psycopg2

        conn = psycopg2.connect(PG_DSN)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT count(*) FROM tenants t
            LEFT JOIN tenant_sidecar_bindings b ON b.tenant_id = t.id
            WHERE b.tenant_id IS NULL
            """
        )
        missing = cur.fetchone()[0]
        conn.close()
        self.assertEqual(missing, 0, "有租戶缺 sidecar binding（隔離破口）")

    def test_synthetic_demo_has_no_external_sidecar_ids(self):
        """公開合成 Demo 不得繼承舊租戶的外部 sidecar 歸屬。"""
        from sqlalchemy import create_engine, inspect
        from sqlalchemy.orm import Session

        from app.demo.manifest import DEMO_TENANT_ID
        from app.services.demo_tenant import reset_demo_tenant

        engine = create_engine(PG_DSN)
        columns = {column["name"] for column in inspect(engine).get_columns("tenants")}
        if "is_demo" not in columns:
            engine.dispose()
            self.skipTest("live PostgreSQL has not applied the Demo isolation migration")
        connection = engine.connect()
        transaction = connection.begin()
        db = Session(bind=connection)
        try:
            reset_demo_tenant(db)
            row = connection.exec_driver_sql(
                """
                SELECT b.ragflow_dataset_id, b.weknora_kb_id
                FROM tenants t JOIN tenant_sidecar_bindings b ON b.tenant_id = t.id
                WHERE t.id = %s
                """,
                (str(DEMO_TENANT_ID),),
            ).fetchone()
        finally:
            db.close()
            transaction.rollback()
            connection.close()
            engine.dispose()
        self.assertIsNotNone(row, "合成 Demo 缺隔離 binding")
        self.assertIsNone(row[0], "合成 Demo 不得綁 RAGFlow dataset")
        self.assertIsNone(row[1], "合成 Demo 不得綁 WeKnora KB")


if __name__ == "__main__":
    unittest.main()
