#!/usr/bin/env python3
"""Run a marked, self-cleaning current-release core journey.

This runner is suitable for a synthetic/internal tenant only. It uploads one
plain-text asset, waits for ingestion, proves search and grounded chat, revokes
the asset, and proves the exact asset/document identities are no longer visible.
It never stores credentials in its evidence artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx


def _contains_identity(value: Any, identities: set[str]) -> bool:
    if isinstance(value, dict):
        return any(
            _contains_identity(key, identities) or _contains_identity(item, identities)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_identity(item, identities) for item in value)
    return str(value) in identities


def _contains_marker(value: Any, marker: str) -> bool:
    if isinstance(value, dict):
        return any(
            _contains_marker(key, marker) or _contains_marker(item, marker)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_marker(item, marker) for item in value)
    return marker in str(value)


def _asset_ready(payload: dict[str, Any]) -> bool:
    revision = payload.get("revision") or {}
    job = payload.get("job") or {}
    return (
        payload.get("status") in {"ready", "active"}
        and revision.get("ingestion_status") == "ready"
        and job.get("status") in {None, "ready"}
    )


def _request_json(response: httpx.Response, expected: set[int], step: str) -> Any:
    if response.status_code not in expected:
        raise RuntimeError(f"{step} returned HTTP {response.status_code}")
    return response.json() if response.content else {}


def run_journey(
    *,
    client: httpx.Client,
    username: str,
    password: str,
    expected_tenant_id: str,
    marker: str,
    timeout_seconds: int,
    poll_seconds: float,
) -> dict[str, Any]:
    if not marker.startswith("PRA-E2E-") or len(marker) < 20:
        raise ValueError("marker must be a specific value starting with PRA-E2E-")
    started_at = datetime.now(UTC)
    health = _request_json(client.get("/health"), {200}, "health")
    release = health.get("release") or {}
    if release.get("identifiable") is not True:
        raise RuntimeError("release is not identifiable")
    login = _request_json(
        client.post(
            "/api/v1/auth/login/access-token",
            data={"username": username, "password": password},
        ),
        {200},
        "login",
    )
    token = str(login.get("access_token") or "")
    if not token:
        raise RuntimeError("login did not return a full access token")
    headers = {"Authorization": f"Bearer {token}"}
    me = _request_json(client.get("/api/v1/users/me", headers=headers), {200}, "me")
    if str(me.get("tenant_id") or "") != expected_tenant_id:
        raise RuntimeError(
            "credential tenant does not match the explicit synthetic tenant"
        )

    statement = (
        f"{marker} is synthetic test data. The verified actuator clearance is "
        "7.25 millimeters. This record is not a real company procedure."
    )
    asset_id = ""
    document_id = ""
    cleanup: dict[str, Any] = {"attempted": False, "status_code": None}
    observations: dict[str, Any] = {}
    error: Exception | None = None
    try:
        upload = client.post(
            "/api/v1/knowledge/assets",
            headers=headers,
            files={
                "file": (
                    f"{marker}.txt",
                    statement.encode("utf-8"),
                    "text/plain",
                )
            },
            data={
                "title": f"Synthetic Product Reality {marker}",
                "idempotency_key": marker,
                "data_classification": "internal",
            },
        )
        upload_payload = _request_json(upload, {202}, "asset upload")
        asset_id = str(upload_payload.get("id") or upload_payload.get("asset_id") or "")
        document_id = str(
            (upload_payload.get("metadata") or {}).get("legacy_document_id") or ""
        )
        if not asset_id or not document_id:
            raise RuntimeError(
                "upload did not return canonical asset and document identities"
            )

        deadline = time.monotonic() + timeout_seconds
        status_payload: dict[str, Any] = {}
        while time.monotonic() < deadline:
            status_payload = _request_json(
                client.get(f"/api/v1/knowledge/assets/{asset_id}", headers=headers),
                {200},
                "asset status",
            )
            if _asset_ready(status_payload):
                break
            job = status_payload.get("job") or {}
            if status_payload.get("status") in {"failed", "tombstoned"} or job.get(
                "status"
            ) in {"failed", "cancelled"}:
                raise RuntimeError("asset ingestion reached a failed terminal state")
            time.sleep(poll_seconds)
        else:
            raise TimeoutError("asset ingestion did not become ready")
        observations["terminal_state"] = {
            "asset": status_payload.get("status"),
            "revision": (status_payload.get("revision") or {}).get("ingestion_status"),
            "job": (status_payload.get("job") or {}).get("status"),
        }

        search = _request_json(
            client.post(
                "/api/v1/gateway/search",
                headers=headers,
                json={"query": marker, "top_k": 10, "domain": "hybrid"},
            ),
            {200},
            "search before revoke",
        )
        if not (
            _contains_identity(search, {asset_id, document_id})
            or _contains_marker(search, marker)
        ):
            raise RuntimeError("newly ingested marker was not retrievable")
        observations["search_before_revoke"] = "hit"

        chat = _request_json(
            client.post(
                "/api/v1/chat/chat",
                headers=headers,
                json={
                    "question": f"According to {marker}, what is the verified actuator clearance?",
                    "top_k": 5,
                },
            ),
            {200},
            "grounded chat",
        )
        sources = chat.get("sources") or []
        if "7.25" not in str(chat.get("answer") or ""):
            raise RuntimeError("chat did not return the grounded synthetic value")
        if not sources or not (
            _contains_identity(sources, {asset_id, document_id})
            or _contains_marker(sources, marker)
        ):
            raise RuntimeError("chat answer did not cite the synthetic source")
        observations["chat"] = {"grounded_value": True, "source_count": len(sources)}
    except Exception as exc:
        error = exc
    finally:
        if asset_id:
            cleanup["attempted"] = True
            deleted = client.delete(
                f"/api/v1/knowledge/assets/{asset_id}", headers=headers
            )
            cleanup["status_code"] = deleted.status_code
            if deleted.status_code not in {200, 404} and error is None:
                error = RuntimeError(
                    f"asset cleanup returned HTTP {deleted.status_code}"
                )

    if asset_id and error is None:
        deadline = time.monotonic() + min(timeout_seconds, 180)
        while time.monotonic() < deadline:
            get_after = client.get(
                f"/api/v1/knowledge/assets/{asset_id}", headers=headers
            )
            search_after_response = client.post(
                "/api/v1/gateway/search",
                headers=headers,
                json={"query": marker, "top_k": 10, "domain": "hybrid"},
            )
            search_after = (
                search_after_response.json()
                if search_after_response.status_code == 200
                else {}
            )
            leaked = _contains_identity(search_after, {asset_id, document_id})
            if get_after.status_code == 404 and not leaked:
                observations["revoke"] = {
                    "asset_http": 404,
                    "search_identity_leak": False,
                }
                break
            time.sleep(poll_seconds)
        else:
            error = RuntimeError(
                "revoked asset remained visible after convergence window"
            )

    completed_at = datetime.now(UTC)
    result = {
        "schema_version": "pra-core-journey/v1",
        "status": "PASS" if error is None else "FAIL",
        "execution_class": "production_synthetic",
        "release_id": str(release.get("release_id") or ""),
        "source_commit": str(release.get("source_commit") or ""),
        "tenant_ref_sha256": hashlib.sha256(expected_tenant_id.encode()).hexdigest(),
        "marker": marker,
        "asset_id": asset_id,
        "document_id": document_id,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "duration_ms": round((completed_at - started_at).total_seconds() * 1000),
        "observations": observations,
        "cleanup": cleanup,
        "error": str(error) if error else None,
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://kachu.tw")
    parser.add_argument("--expected-tenant-id", required=True)
    parser.add_argument("--marker", default=f"PRA-E2E-{uuid.uuid4().hex}")
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--poll-seconds", type=float, default=5)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    username = os.environ.get("PRA_E2E_USERNAME") or os.environ.get(
        "FIRST_SUPERUSER_EMAIL", ""
    )
    password = os.environ.get("PRA_E2E_PASSWORD") or os.environ.get(
        "FIRST_SUPERUSER_PASSWORD", ""
    )
    if not username or not password:
        parser.error("PRA_E2E_USERNAME and PRA_E2E_PASSWORD are required")
    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=180) as client:
        result = run_journey(
            client=client,
            username=username,
            password=password,
            expected_tenant_id=args.expected_tenant_id,
            marker=args.marker,
            timeout_seconds=args.timeout_seconds,
            poll_seconds=args.poll_seconds,
        )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
