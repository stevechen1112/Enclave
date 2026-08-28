from __future__ import annotations

import importlib.util
from pathlib import Path

import httpx
import pytest
import respx

from app.services.capacity_gate import load_capacity_spec

ROOT = Path(__file__).resolve().parents[1]


def _module():
    path = ROOT / "scripts" / "run_p5_cost_guardrails.py"
    spec = importlib.util.spec_from_file_location("test_run_p5_cost", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _identity() -> dict:
    return {
        "container": "enclave-p5-web-1",
        "container_id": "web-container-id",
        "compose_project": "enclave-p5",
        "compose_service": "web",
        "running": True,
        "image_id": "sha256:" + "b" * 64,
    }


@respx.mock
def test_live_cost_drill_is_tenant_and_provenance_bound():
    module = _module()
    tenant_id = "11111111-1111-1111-1111-111111111111"
    base = "https://p5.invalid"
    spec = load_capacity_spec()
    respx.post(base + "/api/v1/auth/login/access-token").mock(
        return_value=httpx.Response(200, json={"access_token": "test-token"})
    )
    respx.get(base + "/api/v1/users/me").mock(
        return_value=httpx.Response(200, json={"tenant_id": tenant_id})
    )
    quota = respx.get(base + f"/api/v1/admin/tenants/{tenant_id}/quota").mock(
        return_value=httpx.Response(
            200,
            json={
                "monthly_query_limit": 100,
                "monthly_token_limit": 1000,
                "monthly_cost_limit_usd": 10,
                "current_monthly_cost_usd": 1,
            },
        )
    )
    respx.get(base + "/api/v1/analytics/cost-units").mock(
        return_value=httpx.Response(
            200,
            json={
                "unit_reports": [
                    {"unit": unit, "rate_usd": rate, "usage": 1}
                    for unit, rate in spec["cost_units"].items()
                ]
            },
        )
    )
    updates = respx.put(base + f"/api/v1/admin/tenants/{tenant_id}/quota").mock(
        side_effect=[httpx.Response(200), httpx.Response(200)]
    )
    respx.post(base + "/api/v1/chat/chat").mock(
        return_value=httpx.Response(429, json={"detail": {"axis": "cost"}})
    )

    report, transcript = module.run_live_cost_drill(
        base_url=base,
        tenant_id=tenant_id,
        email="owner@example.invalid",
        password="injected",
        timeout=10,
        source_commit="a" * 40,
        compose_project="enclave-p5",
        environment_artifact_sha256="e" * 64,
        runtime_container_identity=_identity(),
    )

    assert report["status"] == "PASS"
    assert report["tenant_id"] == tenant_id
    assert report["source_commit"] == "a" * 40
    assert report["quota_restored"] is True
    assert transcript["steps"]["blocked_probe"]["status_code"] == 429
    assert quota.called
    assert updates.call_count == 2


@respx.mock
def test_live_cost_drill_rejects_cross_tenant_administrator():
    module = _module()
    base = "https://p5.invalid"
    respx.post(base + "/api/v1/auth/login/access-token").mock(
        return_value=httpx.Response(200, json={"access_token": "test-token"})
    )
    respx.get(base + "/api/v1/users/me").mock(
        return_value=httpx.Response(200, json={"tenant_id": "other-tenant"})
    )
    with pytest.raises(ValueError, match="dedicated tenant"):
        module.run_live_cost_drill(
            base_url=base,
            tenant_id="expected-tenant",
            email="owner@example.invalid",
            password="injected",
            timeout=10,
            source_commit="a" * 40,
            compose_project="enclave-p5",
            environment_artifact_sha256="e" * 64,
            runtime_container_identity=_identity(),
        )
