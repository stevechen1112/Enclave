from __future__ import annotations

from unittest.mock import MagicMock

from scripts import initial_data


def test_initial_data_uses_audited_maintenance_bypass(monkeypatch):
    db = MagicMock()
    tenant = MagicMock()

    monkeypatch.setattr(initial_data.settings, "FIRST_SUPERUSER_EMAIL", "owner@example.test")
    monkeypatch.setattr(initial_data.settings, "FIRST_SUPERUSER_PASSWORD", "valid-password-123")
    monkeypatch.setattr(initial_data.settings, "ORGANIZATION_NAME", "Test Organization")
    monkeypatch.setattr(initial_data, "MaintenanceSessionLocal", lambda: db)
    bypass = MagicMock(return_value=True)
    monkeypatch.setattr(initial_data, "apply_rls_bypass", bypass)
    monkeypatch.setattr(initial_data.crud_tenant, "get_by_name", lambda *_args, **_kwargs: tenant)
    monkeypatch.setattr(initial_data.crud_user, "get_by_email", lambda *_args, **_kwargs: MagicMock())

    initial_data.init_db()

    bypass.assert_called_once()
    assert bypass.call_args.kwargs["operation"] == "initialize_superuser"
    db.close.assert_called_once()
