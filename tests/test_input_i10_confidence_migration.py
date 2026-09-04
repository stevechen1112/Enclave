from pathlib import Path

import pytest

from app.db.migrations.versions import input_i10_confidence_contract_001 as migration


MIGRATION = Path("app/db/migrations/versions/input_i10_confidence_contract_001.py")


def test_confidence_repair_is_scoped_and_reversible():
    source = MIGRATION.read_text(encoding="utf-8")

    assert "provider = 'core.video'" in source
    assert "provider_version = '1.0'" in source
    assert "confidence = 0" in source
    assert "confidence_provider_supplied" in source
    assert "confidence_repaired_by" in source
    assert "confidence IS NULL" in source
    assert "input_i10_confidence_contract_001" in source
    assert "provider = 'openai'" in source
    assert "provider_version = 'long_interview_stt.i5'" in source
    assert "confidence_metadata_repaired_by" in source


def test_cross_tenant_repair_requires_audited_rls_bypass():
    source = MIGRATION.read_text(encoding="utf-8")

    assert "to_regrole('enclave_rls_bypass')" in source
    assert "c.relowner = r.oid AS is_table_owner" in source
    assert "platform_maintenance_audit" in source
    assert "set_config('app.bypass_rls', 'on', true)" in source


class _AccessResult:
    def __init__(self, access):
        self._access = access

    def mappings(self):
        return self

    def one(self):
        return self._access


class _MigrationBind:
    def __init__(self, access):
        self.access = access
        self.statements = []

    def execute(self, statement, parameters=None):
        sql = str(statement)
        self.statements.append((sql, parameters))
        if "FROM pg_class" in sql:
            return _AccessResult(self.access)
        return None


def _access(**overrides):
    return {
        "relrowsecurity": True,
        "relforcerowsecurity": True,
        "rolsuper": False,
        "rolbypassrls": False,
        "is_table_owner": False,
        "is_bypass_member": False,
        **overrides,
    }


def test_migration_rejects_unauthorised_cross_tenant_repair(monkeypatch):
    bind = _MigrationBind(_access())
    monkeypatch.setattr(migration.op, "get_bind", lambda: bind)

    with pytest.raises(RuntimeError, match="not authorised"):
        migration._enable_audited_bypass("test")

    assert not any(
        "INSERT INTO platform_maintenance_audit" in sql for sql, _ in bind.statements
    )


def test_non_forced_table_owner_is_audited_without_marker_bypass(monkeypatch):
    bind = _MigrationBind(_access(relforcerowsecurity=False, is_table_owner=True))
    monkeypatch.setattr(migration.op, "get_bind", lambda: bind)

    migration._enable_audited_bypass("test")

    assert any(
        "INSERT INTO platform_maintenance_audit" in sql for sql, _ in bind.statements
    )
    assert not any("set_config" in sql for sql, _ in bind.statements)


def test_marker_role_enables_audited_transaction_local_bypass(monkeypatch):
    bind = _MigrationBind(_access(is_bypass_member=True))
    monkeypatch.setattr(migration.op, "get_bind", lambda: bind)

    migration._enable_audited_bypass("test")

    assert any(
        "INSERT INTO platform_maintenance_audit" in sql for sql, _ in bind.statements
    )
    assert any("set_config" in sql for sql, _ in bind.statements)
