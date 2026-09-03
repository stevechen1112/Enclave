from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from app.services.rls_runtime_gate import evaluate_runtime_rls


ROOT = Path(__file__).resolve().parents[1]


@dataclass
class _Dialect:
    name: str = "postgresql"


@dataclass
class _Bind:
    dialect: _Dialect = field(default_factory=_Dialect)


class _Result:
    def __init__(self, row):
        self.row = row

    def mappings(self):
        return self

    def one(self):
        return self.row


class _Session:
    bind = _Bind()

    def __init__(self, role, schema):
        self.results = iter((_Result(role), _Result(schema)))

    def execute(self, _statement):
        return next(self.results)


def test_runtime_gate_accepts_least_privilege_forced_role() -> None:
    report = evaluate_runtime_rls(
        _Session(
            {
                "rolname": "enclave_app",
                "rolsuper": False,
                "rolbypassrls": False,
                "application_member": True,
                "bypass_member": False,
            },
            {
                "protected_table_count": 111,
                "enabled_table_count": 111,
                "forced_table_count": 111,
            },
        )
    )
    assert report["status"] == "PASS"
    assert report["errors"] == []


@pytest.mark.parametrize(
    "role_patch,forced,expected",
    (
        ({"rolsuper": True}, 111, "superuser"),
        ({"rolbypassrls": True}, 111, "BYPASSRLS"),
        ({"application_member": False}, 111, "lacks enclave_application"),
        ({"bypass_member": True}, 111, "bypass member"),
        ({}, 110, "FORCE RLS"),
    ),
)
def test_runtime_gate_rejects_unsafe_role_or_schema(
    role_patch: dict, forced: int, expected: str
) -> None:
    role = {
        "rolname": "enclave_app",
        "rolsuper": False,
        "rolbypassrls": False,
        "application_member": True,
        "bypass_member": False,
        **role_patch,
    }
    report = evaluate_runtime_rls(
        _Session(
            role,
            {
                "protected_table_count": 111,
                "enabled_table_count": 111,
                "forced_table_count": forced,
            },
        )
    )
    assert report["status"] == "FAIL"
    assert expected in " ".join(report["errors"])


def test_activation_migration_is_chained_and_dynamic() -> None:
    migration = (
        ROOT / "app/db/migrations/versions/tenant_force_rls_pra_002.py"
    ).read_text(encoding="utf-8")
    assert 'down_revision: str | None = "tenant_policy_reconcile_pra_001"' in migration
    assert "pg_catalog.pg_policies" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration


def test_all_long_running_processes_install_the_runtime_gate() -> None:
    api = (ROOT / "app/main.py").read_text(encoding="utf-8")
    celery = (ROOT / "app/celery_app.py").read_text(encoding="utf-8")
    assert "assert_runtime_rls_ready()" in api
    assert "worker_process_init.connect(_assert_rls_runtime_ready" in celery
    assert "beat_init.connect(_assert_rls_runtime_ready" in celery


def test_activation_command_has_explicit_rollback_mode() -> None:
    command = (ROOT / "scripts/activate_tenant_force_rls.py").read_text(
        encoding="utf-8"
    )
    assert 'mode.add_argument("--disable"' in command
    assert '"NO-FORCE-RLS"' in command
    assert "NO FORCE ROW LEVEL SECURITY" in command
