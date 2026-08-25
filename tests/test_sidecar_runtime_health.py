"""Gate 3: sidecar address, runtime health, and capability honesty."""
from __future__ import annotations

import pytest

from app.gateway.adapters.base import MockAdapter
from app.gateway.health import GatewayHealthChecker
from app.gateway.sidecar_config import (
    SidecarConfigurationError,
    resolve_sidecar_url,
    validate_enabled_sidecars,
)
from app.services.product_license import ProductModule, is_module_enabled


@pytest.fixture(autouse=True)
def _isolate_runtime_snapshot():
    from app.gateway.runtime_health import (
        get_runtime_health_snapshot,
        reset_runtime_health_snapshot,
        set_runtime_health_snapshot,
    )

    original = get_runtime_health_snapshot()
    reset_runtime_health_snapshot()
    yield
    if original is None:
        reset_runtime_health_snapshot()
    else:
        set_runtime_health_snapshot(original)


def _disable_sidecars(monkeypatch) -> None:
    monkeypatch.setenv("RAGFLOW_ENABLED", "false")
    monkeypatch.setenv("PIPESHUB_ENABLED", "false")
    monkeypatch.setenv("WEKNORA_ENABLED", "false")


def test_module_flags_are_normalized(monkeypatch):
    monkeypatch.setenv("RAGFLOW_ENABLED", " TRUE ")
    assert is_module_enabled(ProductModule.DOCUMENT_INTELLIGENCE) is True


def test_production_loopback_is_rejected(monkeypatch):
    monkeypatch.setenv("RAGFLOW_BASE_URL", " http://127.0.0.1:9380/ ")
    with pytest.raises(SidecarConfigurationError, match="service DNS"):
        resolve_sidecar_url("ragflow", app_env="production")


def test_url_credentials_are_rejected(monkeypatch):
    monkeypatch.setenv("PIPESHUB_BASE_URL", "https://user:secret@pipeshub.example")
    with pytest.raises(SidecarConfigurationError, match="must not contain credentials"):
        resolve_sidecar_url("pipeshub", app_env="development")


def test_disabled_sidecar_url_does_not_block_core(monkeypatch):
    _disable_sidecars(monkeypatch)
    monkeypatch.setenv("RAGFLOW_BASE_URL", "not-a-url")
    assert validate_enabled_sidecars(app_env="production") == {}


def test_enabled_sidecars_resolve_compose_dns(monkeypatch):
    monkeypatch.setenv("RAGFLOW_ENABLED", "true")
    monkeypatch.setenv("PIPESHUB_ENABLED", "true")
    monkeypatch.setenv("WEKNORA_ENABLED", "true")
    monkeypatch.delenv("RAGFLOW_BASE_URL", raising=False)
    monkeypatch.delenv("PIPESHUB_BASE_URL", raising=False)
    monkeypatch.delenv("WEKNORA_BASE_URL", raising=False)
    assert validate_enabled_sidecars(app_env="production") == {
        "ragflow": "http://ragflow:9380",
        "pipeshub": "http://pipeshub-api:3000",
        "weknora": "http://weknora:8080",
    }


def test_factory_refuses_enabled_loopback_in_production(monkeypatch):
    from app.gateway.adapter_factory import build_projection_adapters

    _disable_sidecars(monkeypatch)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("RAGFLOW_ENABLED", "true")
    monkeypatch.setenv("RAGFLOW_BASE_URL", "http://localhost:9380")
    with pytest.raises(SidecarConfigurationError, match="service DNS"):
        build_projection_adapters()


@pytest.mark.asyncio
async def test_disabled_optional_packs_do_not_degrade_core(monkeypatch):
    _disable_sidecars(monkeypatch)
    report = await GatewayHealthChecker().check_adapters(
        {"document": MockAdapter(domain="document")}
    )
    assert report["gateway"] == "healthy"
    assert report["healthy_adapters"] == 1
    assert report["packs"][ProductModule.DOCUMENT_INTELLIGENCE.value]["state"] == "disabled"
    assert "search" in report["available_capabilities"]


@pytest.mark.asyncio
async def test_enabled_but_unhealthy_pack_is_not_available(monkeypatch):
    _disable_sidecars(monkeypatch)
    monkeypatch.setenv("PIPESHUB_ENABLED", "true")
    connector = MockAdapter(domain="connector")
    connector.set_unhealthy()
    report = await GatewayHealthChecker().check_adapters(
        {
            "document": MockAdapter(domain="document"),
            "connector": connector,
        }
    )
    pack = report["packs"][ProductModule.ENTERPRISE_CONNECT.value]
    assert report["gateway"] == "degraded"
    assert pack == {"enabled": True, "available": False, "state": "unavailable"}
    assert report["adapters"]["connector"]["features"] == []


@pytest.mark.asyncio
async def test_healthy_enabled_pack_exposes_verified_capabilities(monkeypatch):
    _disable_sidecars(monkeypatch)
    monkeypatch.setenv("PIPESHUB_ENABLED", "true")
    report = await GatewayHealthChecker().check_adapters(
        {
            "document": MockAdapter(domain="document"),
            "connector": MockAdapter(domain="connector"),
        }
    )
    pack = report["packs"][ProductModule.ENTERPRISE_CONNECT.value]
    assert report["gateway"] == "healthy"
    assert pack["available"] is True
    assert pack["state"] == "enabled"
    assert "search" in report["adapters"]["connector"]["features"]


@pytest.mark.asyncio
async def test_probe_errors_are_redacted_from_operator_response(monkeypatch):
    class BrokenAdapter(MockAdapter):
        async def health(self):
            return {
                "status": "unhealthy",
                "error": "connect failed http://internal-secret-host:9999",
                "base_url": "http://internal-secret-host:9999",
            }

    _disable_sidecars(monkeypatch)
    report = await GatewayHealthChecker().check_adapters(
        {"document": BrokenAdapter(domain="document")}
    )
    document = report["adapters"]["document"]
    assert document["reason"] == "probe_failed"
    assert "error" not in document
    assert "base_url" not in document
    assert "internal-secret-host" not in str(report)


def test_gateway_detailed_health_requires_superuser():
    from app.api.deps_permissions import require_superuser
    from app.api.v1.endpoints.gateway import router

    route = next(route for route in router.routes if route.path == "/gateway/health")
    dependency_calls = {dependency.call for dependency in route.dependant.dependencies}
    assert require_superuser in dependency_calls


def test_product_surface_does_not_claim_unprobed_runtime(monkeypatch):
    from app.api.v1.product_surface import WIKI_PRODUCT_STATUS, with_runtime_status
    from app.gateway.runtime_health import set_runtime_health_snapshot

    set_runtime_health_snapshot({"adapters": {}})
    status = with_runtime_status(WIKI_PRODUCT_STATUS)
    assert status["available"] is False
    assert status["status"] == "runtime_unavailable"
    assert WIKI_PRODUCT_STATUS["status"] == "beta"


def test_product_surface_reports_verified_runtime(monkeypatch):
    from app.api.v1.product_surface import WIKI_PRODUCT_STATUS, with_runtime_status
    from app.gateway.runtime_health import set_runtime_health_snapshot

    set_runtime_health_snapshot(
        {"adapters": {"wiki": {"status": "healthy", "available": True}}}
    )
    status = with_runtime_status(WIKI_PRODUCT_STATUS)
    assert status["available"] is True
    assert status["runtime_state"] == "healthy"
    assert status["status"] == "beta"
