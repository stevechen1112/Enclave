"""RLS 租戶隔離測試（ADR-012）——含真實 PostgreSQL 繞過攻擊驗證。

分兩層：
1. 單元測試（fake session）：context 設定語義、bypass 關閉順序、型別防線。
2. 整合測試（live PG，連不上自動 skip）：在暫存探針表上啟用與 migration
   完全相同的 policy，驗證 CG-RLS 閘門的核心攻擊面——
   raw SQL 跨租戶讀取、無 context 查詢、跨租戶寫入、bypass 通道。
"""

import os
import sys
import unittest
import uuid
from unittest.mock import MagicMock, patch

sys.path.insert(0, ".")

from app.services.rls import (
    BYPASS_GUC,
    TENANT_GUC,
    apply_rls_bypass,
    apply_rls_context,
    task_session,
)

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()


def _fake_pg_session():
    """記錄所執行 SQL 的假 PostgreSQL session。"""
    db = MagicMock()
    db.bind.dialect.name = "postgresql"
    db.executed = []

    def _execute(stmt, params=None):
        db.executed.append((str(stmt), params))
        result = MagicMock()
        result.scalar.return_value = True if "pg_has_role" in str(stmt) else None
        return result

    db.execute.side_effect = _execute
    return db


class TestApplyContext(unittest.TestCase):
    def test_sets_tenant_guc_transaction_scoped(self):
        db = _fake_pg_session()
        db.info = {}
        self.assertTrue(apply_rls_context(db, TENANT_A))
        # 先關 bypass 再設租戶——順序是安全語義的一部分
        sql0, params0 = db.executed[0]
        sql1, params1 = db.executed[1]
        self.assertIn(f"set_config('{BYPASS_GUC}'", sql0)
        self.assertEqual(params0["bv"], "off")
        self.assertIn(f"set_config('{TENANT_GUC}'", sql1)
        self.assertIn("true", sql1)  # is_local=true：transaction-scoped
        self.assertEqual(params1["tid"], str(TENANT_A))

    def test_rejects_non_uuid(self):
        db = _fake_pg_session()
        for bad in ("not-a-uuid", str(TENANT_A), 123, None):
            with self.assertRaises(TypeError):
                apply_rls_context(db, bad)
        self.assertEqual(db.executed, [])  # 型別防線先於任何 SQL

    def test_skips_non_postgres(self):
        db = MagicMock()
        db.bind.dialect.name = "sqlite"
        self.assertFalse(apply_rls_context(db, TENANT_A))
        db.execute.assert_not_called()

    def test_bypass_sets_guc(self):
        db = _fake_pg_session()
        self.assertTrue(
            apply_rls_bypass(
                db,
                actor_identity="test-operator",
                operation="test_bypass",
                reason="verify audited bypass",
            )
        )
        self.assertIn("pg_has_role", db.executed[0][0])
        self.assertIn(f"set_config('{BYPASS_GUC}', 'on', true)", db.executed[1][0])
        self.assertIn("platform_maintenance_audit", db.executed[2][0])


class TestTaskSession(unittest.TestCase):
    def test_opens_applies_closes(self):
        db = _fake_pg_session()
        factory = MagicMock(return_value=db)
        with task_session(factory, TENANT_A) as session:
            self.assertIs(session, db)
        self.assertEqual(len(db.executed), 2)  # bypass off + tenant set
        db.close.assert_called_once()


class TestDepsWiring(unittest.TestCase):
    """get_current_user：JWT tenant claim 先建立 context，再查找用戶。"""

    def test_bypass_then_context(self):
        from app.api import deps

        db = _fake_pg_session()
        db.info = {}
        user = MagicMock()
        user.tenant_id = TENANT_A
        token = MagicMock()

        with (
            patch.object(
                deps.jwt,
                "decode",
                return_value={"sub": "a@b.c", "tenant_id": str(TENANT_A)},
            ),
            patch.object(deps.crud_user, "get_by_email", return_value=user),
        ):
            result = deps.get_current_user(db=db, token=token)

        self.assertIs(result, user)
        sqls = [s for s, _ in db.executed]
        params = [p for _, p in db.executed]
        self.assertIn(f"set_config('{BYPASS_GUC}'", sqls[0])
        self.assertEqual(params[0]["bv"], "off")
        self.assertIn(f"set_config('{TENANT_GUC}'", sqls[1])
        self.assertEqual(params[1]["tid"], str(TENANT_A))


class TestLoginTenantResolution(unittest.TestCase):
    """login 端點：只解析 tenant UUID，隨即以 RLS context 驗證密碼。"""

    def test_login_applies_bypass_before_authenticate(self):
        from app.api.v1.endpoints import auth

        db = _fake_pg_session()
        db.info = {}
        user = MagicMock()
        user.is_active = True
        user.email = "a@b.c"
        user.tenant_id = TENANT_A
        user.mfa_enabled = False  # CG-AUTH-SSO：MFA 開啟時登入改回 partial token
        form = MagicMock()
        form.username = "a@b.c"
        form.password = "pw"

        import app.services.rls as rls

        with (
            patch.object(rls, "resolve_login_tenant", return_value=TENANT_A),
            patch.object(
                auth.crud_user, "authenticate", return_value=user
            ) as auth_mock,
            patch.object(auth.security, "create_access_token", return_value="tok"),
        ):
            result = auth.login_access_token(db=db, form_data=form)

        self.assertEqual(result["access_token"], "tok")
        # tenant context 必須發生在 authenticate 之前
        self.assertIn(f"set_config('{BYPASS_GUC}'", db.executed[0][0])
        self.assertEqual(db.executed[0][1]["bv"], "off")
        self.assertIn(f"set_config('{TENANT_GUC}'", db.executed[1][0])
        auth_mock.assert_called_once()


class TestContextReapplyAfterCommit(unittest.TestCase):
    """SET LOCAL 隨 transaction 結束消失——after_begin 必須從 session.info 重設。"""

    def test_context_recorded_in_session_info(self):
        from app.services.rls import _INFO_TENANT_KEY

        db = _fake_pg_session()
        db.info = {}
        apply_rls_context(db, TENANT_A)
        self.assertEqual(db.info[_INFO_TENANT_KEY], str(TENANT_A))

    def test_after_begin_reapplies_from_info(self):
        from app.services.rls import _INFO_TENANT_KEY, _after_begin

        session = MagicMock()
        session.info = {_INFO_TENANT_KEY: str(TENANT_A)}
        conn = MagicMock()
        conn.dialect.name = "postgresql"
        executed = []
        conn.execute.side_effect = lambda stmt, params=None: executed.append(
            (str(stmt), params)
        )

        _after_begin(session, MagicMock(), conn)

        self.assertEqual(len(executed), 2)
        self.assertIn(f"set_config('{BYPASS_GUC}'", executed[0][0])
        self.assertEqual(executed[0][1]["bv"], "off")
        self.assertIn(f"set_config('{TENANT_GUC}'", executed[1][0])
        self.assertEqual(executed[1][1]["tid"], str(TENANT_A))

    def test_after_begin_noop_without_info(self):
        from app.services.rls import _after_begin

        session = MagicMock()
        session.info = {}
        conn = MagicMock()
        conn.dialect.name = "postgresql"
        _after_begin(session, MagicMock(), conn)
        conn.execute.assert_not_called()

    def test_after_begin_skips_non_postgres(self):
        from app.services.rls import _INFO_TENANT_KEY, _after_begin

        session = MagicMock()
        session.info = {_INFO_TENANT_KEY: str(TENANT_A)}
        conn = MagicMock()
        conn.dialect.name = "sqlite"
        _after_begin(session, MagicMock(), conn)
        conn.execute.assert_not_called()

    def test_register_session_events_idempotent(self):
        import app.services.rls as rls

        rls.register_session_events()
        rls.register_session_events()  # 第二次不得重複掛載或報錯
        self.assertTrue(rls._events_registered)


class TestAuditBypassLeak(unittest.TestCase):
    """audit 結束後無論先前有無 context，bypass 都必須關閉（不得殘留）。"""

    def _audit_db(self, prior):
        db = _fake_pg_session()
        db.info = {}

        def _execute(stmt, params=None):
            sql = str(stmt)
            db.executed.append((sql, params))
            result = MagicMock()
            if "pg_has_role" in sql:
                result.scalar.return_value = True
            elif "current_setting" in sql:
                result.scalar.return_value = prior
            elif "information_schema" in sql:
                result.fetchall.return_value = []  # 無 RLS 表 → 直接走到 finally
            else:
                result.scalar.return_value = 0
            return result

        db.execute.side_effect = _execute
        return db

    def test_bypass_closed_when_no_prior_context(self):
        from app.services.rls import audit_tenant_visibility

        db = self._audit_db(prior=None)
        audit_tenant_visibility(db)
        bypass_off = [
            s
            for s, p in db.executed
            if f"set_config('{BYPASS_GUC}'" in s and p and p.get("bv") == "off"
        ]
        self.assertTrue(bypass_off, "無 prior context 時 bypass 未被關閉")

    def test_prior_context_restored(self):
        from app.services.rls import _INFO_TENANT_KEY, audit_tenant_visibility

        db = self._audit_db(prior=str(TENANT_A))
        audit_tenant_visibility(db)
        self.assertEqual(db.info.get(_INFO_TENANT_KEY), str(TENANT_A))
        restores = [
            p
            for s, p in db.executed
            if f"set_config('{TENANT_GUC}'" in s and p and p.get("tid") == str(TENANT_A)
        ]
        self.assertTrue(restores, "prior tenant context 未被還原")


# ---------------------------------------------------------------------------
# Live PostgreSQL 整合測試：真實 policy 的繞過攻擊驗證
# ---------------------------------------------------------------------------

PG_DSN = os.environ.get(
    "ENCLAVE_TEST_PG_DSN",
    "postgresql://postgres:postgres@localhost:5435/enclave",
)

# 與 migration rls_tenant_isolation_001 完全相同的 policy SQL
_PROBE_POLICY = """
CREATE POLICY tenant_isolation ON _rls_probe
  USING (
    tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
    OR current_setting('app.bypass_rls', true) = 'on'
  )
  WITH CHECK (
    tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
    OR current_setting('app.bypass_rls', true) = 'on'
  )
"""


def _pg_available() -> bool:
    try:
        import psycopg2

        conn = psycopg2.connect(PG_DSN, connect_timeout=3)
        conn.close()
        return True
    except Exception:
        return False


@unittest.skipUnless(_pg_available(), "live PostgreSQL unavailable")
class TestLivePolicyEnforcement(unittest.TestCase):
    """在暫存探針表上驗證 policy 真實行為（不碰任何正式表）。

    注意：以**非 superuser** 角色連線驗證——superuser／BYPASSRLS 角色
    天生跳過 RLS，這正是 ADR-012 要求 enforce 階段應用程式不得使用
    superuser 連線的原因（本測試即為該要求的實證）。
    """

    _ROLE = "_rls_probe_role"
    _ROLE_PW = "probe_pw"

    @classmethod
    def setUpClass(cls):
        import psycopg2
        from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

        admin = psycopg2.connect(PG_DSN)
        admin.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = admin.cursor()
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (cls._ROLE,))
        if not cur.fetchone():
            cur.execute(f"CREATE ROLE {cls._ROLE} LOGIN PASSWORD %s", (cls._ROLE_PW,))
        cur.execute(f"GRANT USAGE ON SCHEMA public TO {cls._ROLE}")
        cur.close()
        admin.close()

    @classmethod
    def tearDownClass(cls):
        import psycopg2
        from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

        admin = psycopg2.connect(PG_DSN)
        admin.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = admin.cursor()
        cur.execute("DROP TABLE IF EXISTS _rls_probe")
        cur.execute(f"REVOKE USAGE ON SCHEMA public FROM {cls._ROLE}")
        cur.execute(f"DROP ROLE IF EXISTS {cls._ROLE}")
        cur.close()
        admin.close()

    def setUp(self):
        import psycopg2
        from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

        # 管理連線（建表／種子資料）；攻擊測試一律走非 superuser 連線
        admin = psycopg2.connect(PG_DSN)
        admin.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = admin.cursor()
        cur.execute("DROP TABLE IF EXISTS _rls_probe")
        cur.execute(
            "CREATE TABLE _rls_probe (id serial primary key, tenant_id uuid NOT NULL, val text)"
        )
        cur.execute("ALTER TABLE _rls_probe ENABLE ROW LEVEL SECURITY")
        cur.execute("ALTER TABLE _rls_probe FORCE ROW LEVEL SECURITY")
        cur.execute(_PROBE_POLICY)
        cur.execute(
            "INSERT INTO _rls_probe (tenant_id, val) VALUES (%s, 'a1'), (%s, 'a2')",
            (str(TENANT_A), str(TENANT_A)),
        )
        cur.execute(
            "INSERT INTO _rls_probe (tenant_id, val) VALUES (%s, 'b1')",
            (str(TENANT_B),),
        )
        cur.execute(f"GRANT SELECT, INSERT, UPDATE ON _rls_probe TO {self._ROLE}")
        cur.execute(
            f"GRANT USAGE, SELECT ON SEQUENCE _rls_probe_id_seq TO {self._ROLE}"
        )
        cur.close()
        admin.close()

        # 受測連線：非 superuser，FORCE RLS 對其生效
        dsn = PG_DSN.replace(
            "postgresql://postgres:postgres@",
            f"postgresql://{self._ROLE}:{self._ROLE_PW}@",
        )
        self.conn = psycopg2.connect(dsn)
        self.conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)

    def tearDown(self):
        self.conn.close()
        import psycopg2
        from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

        admin = psycopg2.connect(PG_DSN)
        admin.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = admin.cursor()
        cur.execute("DROP TABLE IF EXISTS _rls_probe")
        cur.close()
        admin.close()

    def _select_with_context(self, tenant=None, bypass=False):
        cur = self.conn.cursor()
        if bypass:
            cur.execute("SELECT set_config('app.bypass_rls', 'on', false)")
        if tenant:
            cur.execute("SELECT set_config('app.tenant_id', %s, false)", (str(tenant),))
        cur.execute("SELECT val FROM _rls_probe ORDER BY val")
        rows = [r[0] for r in cur.fetchall()]
        cur.close()
        return rows

    def test_tenant_a_sees_only_own_rows(self):
        self.assertEqual(self._select_with_context(TENANT_A), ["a1", "a2"])

    def test_tenant_b_sees_only_own_rows(self):
        self.assertEqual(self._select_with_context(TENANT_B), ["b1"])

    def test_no_context_sees_nothing(self):
        # fail-closed：未設 context 不是看到全部，而是查無列
        self.assertEqual(self._select_with_context(None), [])

    def test_unknown_tenant_sees_nothing(self):
        self.assertEqual(self._select_with_context(uuid.uuid4()), [])

    def test_bypass_channel_sees_all(self):
        self.assertEqual(
            self._select_with_context(None, bypass=True), ["a1", "a2", "b1"]
        )

    def test_cross_tenant_write_blocked(self):
        # WITH CHECK：context=A 時寫入 tenant_id=B 必須被拒
        import psycopg2.errors

        cur = self.conn.cursor()
        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (str(TENANT_A),))
        with self.assertRaises(psycopg2.errors.InsufficientPrivilege):
            cur.execute(
                "INSERT INTO _rls_probe (tenant_id, val) VALUES (%s, 'evil')",
                (str(TENANT_B),),
            )
        cur.close()

    def test_cross_tenant_update_invisible(self):
        # context=A 對 B 的列 UPDATE 影響 0 列（列根本不可見）
        cur = self.conn.cursor()
        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (str(TENANT_A),))
        cur.execute("UPDATE _rls_probe SET val='hacked' WHERE val='b1'")
        self.assertEqual(cur.rowcount, 0)
        cur.close()
        # 確認 B 的資料未被動到
        self.assertEqual(self._select_with_context(TENANT_B), ["b1"])

    def test_sqlalchemy_context_survives_commit(self):
        # SET LOCAL 隨 commit 消失；after_begin 監聽器必須讓 context 跨 commit 存活
        from sqlalchemy import create_engine, text as sa_text
        from sqlalchemy.orm import sessionmaker

        dsn = PG_DSN.replace(
            "postgresql://postgres:postgres@",
            f"postgresql://{self._ROLE}:{self._ROLE_PW}@",
        )
        engine = create_engine(dsn)
        SF = sessionmaker(bind=engine)
        db = SF()
        try:
            apply_rls_context(db, TENANT_A)
            rows1 = db.execute(
                sa_text("SELECT val FROM _rls_probe ORDER BY val")
            ).fetchall()
            db.commit()  # transaction 結束，GUC 消失
            rows2 = db.execute(
                sa_text("SELECT val FROM _rls_probe ORDER BY val")
            ).fetchall()
            self.assertEqual([r[0] for r in rows1], ["a1", "a2"])
            self.assertEqual([r[0] for r in rows2], ["a1", "a2"])  # commit 後仍受約束
        finally:
            db.close()
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
