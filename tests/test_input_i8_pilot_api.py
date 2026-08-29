from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient


def _payload(owner_id: str) -> dict:
    return {
        "name": "First tenant pilot",
        "evidence_mode": "live",
        "dedicated_environment": True,
        "environment_evidence_sha256": "a" * 64,
        "data_processing_agreement_ref": "contract://signed-dpa",
        "journeys": [
            {
                "key": "nas_batch",
                "review_owner_id": owner_id,
                "metadata_template": {"plant": "required"},
                "glossary_ref": "tenant://glossary/v1",
                "role_acl_ref": "tenant://acl/nas",
            },
            {
                "key": "machine_video",
                "review_owner_id": owner_id,
                "metadata_template": {"machine": "required"},
                "glossary_ref": "tenant://glossary/v1",
                "role_acl_ref": "tenant://acl/video",
            },
        ],
    }


@pytest.mark.asyncio
async def test_pilot_api_starts_but_gate_holds_without_live_window(
    client: AsyncClient, superuser_headers: dict
):
    owner_id = (await client.get("/api/v1/users/me", headers=superuser_headers)).json()["id"]
    created = await client.post(
        "/api/v1/operations/input/pilots",
        headers=superuser_headers,
        json=_payload(owner_id),
    )
    assert created.status_code == 200, created.text
    pilot_id = created.json()["id"]
    started = await client.post(
        f"/api/v1/operations/input/pilots/{pilot_id}/start",
        headers=superuser_headers,
    )
    assert started.status_code == 200
    gate = await client.get(
        f"/api/v1/operations/input/pilots/{pilot_id}/gate",
        headers=superuser_headers,
    )
    assert gate.status_code == 200
    assert gate.json()["status"] == "HOLD"
    assert "pilot observation window is shorter than minimum days" in gate.json()["errors"]


@pytest.mark.asyncio
async def test_pilot_api_rejects_non_hex_environment_evidence(
    client: AsyncClient, superuser_headers: dict
):
    owner_id = (await client.get("/api/v1/users/me", headers=superuser_headers)).json()["id"]
    payload = _payload(owner_id)
    payload["environment_evidence_sha256"] = "z" * 64
    response = await client.post(
        "/api/v1/operations/input/pilots",
        headers=superuser_headers,
        json=payload,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_pilot_api_rejects_metrics_outside_running_live_window(
    client: AsyncClient, superuser_headers: dict
):
    owner_id = (await client.get("/api/v1/users/me", headers=superuser_headers)).json()["id"]
    created = await client.post(
        "/api/v1/operations/input/pilots",
        headers=superuser_headers,
        json=_payload(owner_id),
    )
    pilot_id = created.json()["id"]
    metric = {
        "metric_date": (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat(),
        "journey_key": "nas_batch",
        "total_attempts": 1,
        "successful_attempts": 1,
        "processing_p95_ms": 1,
        "retrieval_checks": 1,
        "cited_retrievals": 1,
        "source_evidence_sha256": "b" * 64,
    }

    before_start = await client.post(
        f"/api/v1/operations/input/pilots/{pilot_id}/daily-metrics",
        headers=superuser_headers,
        json=metric,
    )
    assert before_start.status_code == 409

    await client.post(
        f"/api/v1/operations/input/pilots/{pilot_id}/start",
        headers=superuser_headers,
    )
    future_metric = await client.post(
        f"/api/v1/operations/input/pilots/{pilot_id}/daily-metrics",
        headers=superuser_headers,
        json=metric,
    )
    assert future_metric.status_code == 422


@pytest.mark.asyncio
async def test_pilot_evidence_endpoint_returns_tenant_scoped_operator_view(
    client: AsyncClient, superuser_headers: dict
):
    owner_id = (await client.get("/api/v1/users/me", headers=superuser_headers)).json()["id"]
    created = await client.post(
        "/api/v1/operations/input/pilots",
        headers=superuser_headers,
        json=_payload(owner_id),
    )
    pilot_id = created.json()["id"]
    await client.post(
        f"/api/v1/operations/input/pilots/{pilot_id}/start",
        headers=superuser_headers,
    )
    occurred_at = datetime.now(timezone.utc).isoformat()
    incident = await client.post(
        f"/api/v1/operations/input/pilots/{pilot_id}/incidents",
        headers=superuser_headers,
        json={
            "severity": "medium",
            "category": "permission",
            "near_miss": True,
            "summary": "ACL mapping required review",
            "occurred_at": occurred_at,
        },
    )
    assert incident.status_code == 200, incident.text

    evidence = await client.get(
        f"/api/v1/operations/input/pilots/{pilot_id}/evidence",
        headers=superuser_headers,
    )

    assert evidence.status_code == 200
    body = evidence.json()
    assert body["metric_rows"] == 0
    assert body["incidents"][0]["summary"] == "ACL mapping required review"
    assert body["incidents"][0]["status"] == "open"
    assert body["audits"] == []
    assert body["retrospective"] is None
    assert body["acceptance"] is None
