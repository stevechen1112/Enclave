from uuid import uuid4

from app.services.media_feature_flags import (
    media_capability_enabled_for,
    media_v2_enabled_for,
    parse_tenant_allowlist,
)


def test_media_v2_requires_global_switch_and_explicit_tenant(monkeypatch):
    tenant_id = uuid4()
    monkeypatch.setattr("app.config.settings.MEDIA_PIPELINE_V2", True)
    monkeypatch.setattr("app.config.settings.MEDIA_V2_TENANT_ALLOWLIST", str(tenant_id))

    assert media_v2_enabled_for(tenant_id) is True
    assert media_v2_enabled_for(uuid4()) is False


def test_media_v2_empty_allowlist_fails_closed(monkeypatch):
    monkeypatch.setattr("app.config.settings.MEDIA_PIPELINE_V2", True)
    monkeypatch.setattr("app.config.settings.MEDIA_V2_TENANT_ALLOWLIST", "")

    assert media_v2_enabled_for(uuid4()) is False


def test_media_v2_global_kill_switch_overrides_allowlist(monkeypatch):
    tenant_id = uuid4()
    monkeypatch.setattr("app.config.settings.MEDIA_PIPELINE_V2", False)
    monkeypatch.setattr("app.config.settings.MEDIA_V2_TENANT_ALLOWLIST", str(tenant_id))

    assert media_v2_enabled_for(tenant_id) is False


def test_allowlist_ignores_invalid_entries_and_capability_is_independent(monkeypatch):
    tenant_id = uuid4()
    monkeypatch.setattr("app.config.settings.MEDIA_PIPELINE_V2", True)
    monkeypatch.setattr(
        "app.config.settings.MEDIA_V2_TENANT_ALLOWLIST",
        f"invalid, {tenant_id}, *",
    )

    assert parse_tenant_allowlist("invalid,*,") == frozenset()
    assert media_capability_enabled_for(tenant_id, capability_enabled=True) is True
    assert media_capability_enabled_for(tenant_id, capability_enabled=False) is False
